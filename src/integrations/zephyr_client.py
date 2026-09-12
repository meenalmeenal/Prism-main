"""
Zephyr REST API Client.

Supports Zephyr Essential Cloud today via ``EssentialCloudAdapter``. A
``ZephyrAdapter`` abstraction is introduced so that Squad/Scale/Enterprise
support can be added later (``SquadScaleEnterpriseAdapter``) without
changing pipeline call sites — the pipeline should talk to ``ZephyrClient``
(unchanged public surface) which internally delegates tier-specific
create/read/update calls to the configured adapter.
"""

import os
import logging
import aiohttp
from aiohttp import ClientResponseError
import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)

# Constants
DEFAULT_RETRIES = 3
RETRY_DELAY = 1  # seconds


def _run_async_safely(coro_factory):
    """Run an async coroutine from sync code; safe when a loop is already running."""

    def _runner():
        return asyncio.run(coro_factory())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_runner)
        return future.result(timeout=300)


def retry_on_failure(retries: int = DEFAULT_RETRIES, delay: float = RETRY_DELAY):
    """Decorator to retry failed API calls with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return await func(*args, **kwargs)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    last_exception = e
                    if attempt == retries - 1:
                        break
                    wait_time = delay * (2 ** attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {str(e)}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )
                    await asyncio.sleep(wait_time)
            raise last_exception or Exception("Unknown error occurred")
        return wrapper
    return decorator


@dataclass
class ZephyrTestResult:
    """Represents the result of a test execution in Zephyr."""
    test_case_key: str
    status: str  # PASS, FAIL, BLOCKED, etc.
    comment: str = ""
    execution_id: Optional[str] = None
    started_on: Optional[str] = None
    finished_on: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}


# ---------------------------------------------------------------------------
# Tier adapter abstraction
# ---------------------------------------------------------------------------
#
# ZephyrClient below owns the HTTP session / auth / retry machinery. The
# adapter classes wrap *tier-specific* request shaping (Essential Cloud vs
# Squad/Scale/Enterprise use different endpoints, payload shapes, and in
# some cases different base URLs / auth models). Adapters call back into
# the owning ZephyrClient's `_request` helper so connection handling stays
# centralized.


class ZephyrAdapter(ABC):
    """Tier-specific request shaping for Zephyr's various product lines."""

    @abstractmethod
    async def create_test_case(self, issue_key: str, test_case: Dict) -> Dict:
        ...

    @abstractmethod
    async def create_test_cycle(
        self,
        name: str,
        project_key: Optional[str] = None,
        description: str = "",
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> Dict:
        ...

    @abstractmethod
    async def create_test_execution(
        self, test_case_key: str, cycle_key: str, status: str = "Not Executed"
    ) -> Dict:
        ...

    @abstractmethod
    async def update_test_execution(self, execution_id: str, result: ZephyrTestResult) -> Dict:
        ...

    @abstractmethod
    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        ...

    @abstractmethod
    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        ...

    @abstractmethod
    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        ...

    @abstractmethod
    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        ...

    @abstractmethod
    async def link_cycle_to_issue(self, cycle_key: str, issue_id: str) -> bool:
        ...

    @abstractmethod
    async def link_cycle_to_weburl(self, cycle_key: str, url: str, description: str = "") -> bool:
        ...


class EssentialCloudAdapter(ZephyrAdapter):
    """Zephyr Essential Cloud (formerly ZAPI / Zephyr for Jira Cloud).

    This wraps the request logic that previously lived directly on
    ``ZephyrClient``. Behavior is unchanged from before the refactor —
    this is a pass-through wrapper around the owning client's ``_request``.
    """

    def __init__(self, client: "ZephyrClient"):
        self._client = client

    async def create_test_case(self, issue_key: str, test_case: Dict) -> Dict:
        endpoint = "/testcases"
        data = {
            "projectKey": os.getenv("ZEPHYR_PROJECT_KEY", "ZT"),
            "name": test_case.get("name", "Unnamed Test"),
            "objective": test_case.get("description", ""),
            "precondition": test_case.get("precondition", ""),
            "priority": test_case.get("priority", "Medium"),
            "status": "Draft",
            "testScript": {
                "type": "STEP_BY_STEP",
                "steps": test_case.get("steps", [])
            }
        }
        if issue_key and not (issue_key.startswith("PR-") or issue_key.startswith("SPEC-")):
            data["issueLinks"] = [issue_key]

        return await self._client._request("POST", endpoint, json=data)

    async def create_test_cycle(
        self,
        name: str,
        project_key: Optional[str] = None,
        description: str = "",
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> Dict:
        endpoint = "/testcycles"
        project_key = project_key or os.getenv("ZEPHYR_PROJECT_KEY", "ZT")

        # Zephyr Essential Cloud's /testcycles endpoint does not expose a
        # first-class sprint-link field. As a safe, no-API-risk fallback we
        # encode the sprint into the cycle name/description so the link is
        # still human-traceable in the Zephyr UI, even without a hard
        # foreign-key relationship. If Zephyr later exposes a native sprint
        # field, add it to `data` here instead.
        cycle_name = name
        if sprint_name or sprint_id:
            label = sprint_name or f"Sprint {sprint_id}"
            cycle_name = f"{name} [{label}]"

        data = {
            "name": cycle_name,
            "projectKey": project_key,
            "description": description,
        }
        return await self._client._request("POST", endpoint, json=data)

    async def create_test_execution(
        self, test_case_key: str, cycle_key: str, status: str = "Not Executed"
    ) -> Dict:
        endpoint = "/testexecutions"
        data = {
            "projectKey": os.getenv("ZEPHYR_PROJECT_KEY", "ZT"),
            "testCaseKey": test_case_key,
            "testCycleKey": cycle_key,
            "statusName": status
        }
        logger.info(f"create_test_execution payload: {data}")
        return await self._client._request("POST", endpoint, json=data)

    async def update_test_execution(self, execution_id: str, result: ZephyrTestResult) -> Dict:
        endpoint = f"/testexecutions/{execution_id}"
        data = {
            "statusName": result.status,
            "comment": result.comment,
            "executedOn": result.finished_on or datetime.now(timezone.utc).isoformat()
        }
        return await self._client._request("PUT", endpoint, json=data)

    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        endpoint = f"/testcases/{test_case_id}"
        try:
            return await self._client._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        endpoint = f"/testcycles/{cycle_key}"
        try:
            return await self._client._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        endpoint = f"/testexecutions?testCaseKey={test_case_key}"
        try:
            result = await self._client._request("GET", endpoint)
            return result.get("values", [])
        except aiohttp.ClientError:
            logger.exception(f"Failed to get executions for {test_case_key}")
            return []

    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        endpoint = f"/testcases/{test_case_key}/links/issues"
        try:
            await self._client._request("POST", endpoint, json={"issueKey": issue_key})
            return True
        except aiohttp.ClientError:
            logger.exception(f"Failed to link {test_case_key} to {issue_key}")
            return False

    async def link_cycle_to_issue(self, cycle_key: str, issue_id: str) -> bool:
        if not issue_id or not issue_id.isdigit():
            logger.warning(f"Skipping cycle link — no valid numeric issue_id for cycle {cycle_key}")
            return False
        endpoint = f"/testcycles/{cycle_key}/links/issues"
        try:
            await self._client._request("POST", endpoint, json={"issueId": int(issue_id)})
            return True
        except aiohttp.ClientError:
            logger.exception(f"Failed to link cycle {cycle_key} to issue id {issue_id}")
            return False

    async def link_cycle_to_weburl(self, cycle_key: str, url: str, description: str = "") -> bool:
        endpoint = f"/testcycles/{cycle_key}/links/weburls"
        try:
            await self._client._request("POST", endpoint, json={"url": url, "description": description})
            return True
        except aiohttp.ClientError:
            logger.exception(f"Failed to add weblink {url} to cycle {cycle_key}")
            return False


class SquadScaleEnterpriseAdapter(ZephyrAdapter):
    """Placeholder adapter for Zephyr Squad / Scale / Enterprise.

    NOT IMPLEMENTED YET. These product lines use a different REST API
    (different base URL, auth model — often Basic Auth or a distinct API
    key header rather than the Essential Cloud Bearer token — and
    different resource/payload shapes) from Zephyr Essential Cloud.

    TODO before implementing for real:
      - Confirm which specific product (Squad vs Scale vs Enterprise/DC)
        is targeted, since their APIs differ from each other too.
      - Obtain sandbox credentials to validate request/response shapes.
      - Implement each method below against the real API.

    Instantiating this adapter raises immediately so misconfiguration is
    caught at startup rather than failing confusingly deep in a pipeline run.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "Zephyr Squad/Scale/Enterprise adapter is not implemented yet. "
            "Only Zephyr Essential Cloud (tier='essential') is currently supported. "
            "See SquadScaleEnterpriseAdapter docstring for implementation TODOs."
        )

    async def create_test_case(self, issue_key: str, test_case: Dict) -> Dict:
        raise NotImplementedError

    async def create_test_cycle(
        self, name: str, project_key: Optional[str] = None, description: str = "",
        sprint_id: Optional[int] = None, sprint_name: Optional[str] = None,
    ) -> Dict:
        raise NotImplementedError

    async def create_test_execution(self, test_case_key: str, cycle_key: str, status: str = "Not Executed") -> Dict:
        raise NotImplementedError

    async def update_test_execution(self, execution_id: str, result: ZephyrTestResult) -> Dict:
        raise NotImplementedError

    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        raise NotImplementedError

    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        raise NotImplementedError

    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        raise NotImplementedError

    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        raise NotImplementedError

    async def link_cycle_to_issue(self, cycle_key: str, issue_id: str) -> bool:
        raise NotImplementedError

    async def link_cycle_to_weburl(self, cycle_key: str, url: str, description: str = "") -> bool:
        raise NotImplementedError


def get_zephyr_adapter(client: "ZephyrClient", tier: str = "essential") -> ZephyrAdapter:
    """Factory for the tier-specific adapter. ``tier`` is read from
    ``ZEPHYR_TIER`` env var by default (see ZephyrClient.__init__)."""
    tier = (tier or "essential").lower()
    if tier == "essential":
        return EssentialCloudAdapter(client)
    elif tier in {"squad", "scale", "enterprise"}:
        return SquadScaleEnterpriseAdapter()
    raise ValueError(f"Unknown Zephyr tier: {tier}. Expected one of: essential, squad, scale, enterprise")


class ZephyrClient:
    """Client for interacting with Zephyr's REST API.

    Owns the HTTP session, auth headers, retry logic, and dry-run mode.
    Tier-specific request shaping is delegated to ``self.adapter``
    (see ``get_zephyr_adapter``), selected via the ``tier`` constructor
    argument or the ``ZEPHYR_TIER`` environment variable (default:
    ``essential``, i.e. Zephyr Essential Cloud — the only tier currently
    implemented).
    """

    BASE_URL = "https://prod-api.zephyr4jiracloud.com/v2"

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        tier: Optional[str] = None,
    ):
        self.api_token = api_token or os.getenv("ZEPHYR_API_TOKEN")
        self.base_url = (base_url or os.getenv("ZEPHYR_BASE_URL") or self.BASE_URL).rstrip('/') + '/'
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        self.dry_run = os.getenv("ZEPHYR_DRY_RUN", "false").lower() in {"1", "true", "yes"}

        if not self.api_token and not self.dry_run:
            raise ValueError("ZEPHYR_API_TOKEN is required but not set.")

        self.tier = (tier or os.getenv("ZEPHYR_TIER", "essential")).lower()
        # Adapter construction is deferred to first use for tiers that are
        # not implemented (SquadScaleEnterpriseAdapter raises on init) so
        # that simply importing/constructing ZephyrClient in dry-run/demo
        # contexts doesn't blow up if ZEPHYR_TIER is misconfigured but never
        # actually used. For 'essential' (the default and only supported
        # tier today) we build eagerly since it's always safe.
        self.adapter: Optional[ZephyrAdapter] = None
        if self.tier == "essential":
            self.adapter = get_zephyr_adapter(self, self.tier)

    def _ensure_adapter(self) -> ZephyrAdapter:
        if self.adapter is None:
            self.adapter = get_zephyr_adapter(self, self.tier)
        return self.adapter

    async def __aenter__(self) -> 'ZephyrClient':
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=self.timeout
            )
            logger.debug("Zephyr client connected")

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("Zephyr client connection closed")

    @retry_on_failure()
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        if not self.session or self.session.closed:
            await self.connect()

        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.debug(f"Making {method} request to {url}")

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    body = await response.text()
                    logger.error(f"Zephyr API error {response.status} - Body: {body}")
                    response.raise_for_status()

                if response.status == 204:
                        return {}

                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    return await response.json()
                return await response.text()

        except aiohttp.ClientResponseError as e:
            error_msg = f"Zephyr API request failed: {str(e)}"
            try:
                body = await e.response.text()
                error_msg += f" - Body: {body}"
            except:
                pass
            logger.error(error_msg)
            raise

    # ------------------------------------------------------------------
    # Public API methods (delegate to the configured tier adapter)
    # ------------------------------------------------------------------

    async def create_test_case(self, issue_key: str, test_case: Dict) -> Dict:
        return await self._ensure_adapter().create_test_case(issue_key, test_case)

    async def create_test_cycle(
        self,
        name: str,
        project_key: Optional[str] = None,
        description: str = "",
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> Dict:
        return await self._ensure_adapter().create_test_cycle(
            name, project_key, description, sprint_id=sprint_id, sprint_name=sprint_name
        )

    async def create_test_execution(
        self,
        test_case_key: str,
        cycle_key: str,
        status: str = "Not Executed"
    ) -> Dict:
        return await self._ensure_adapter().create_test_execution(test_case_key, cycle_key, status)

    async def update_test_execution(
        self,
        execution_id: str,
        result: ZephyrTestResult
    ) -> Dict:
        return await self._ensure_adapter().update_test_execution(execution_id, result)

    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        return await self._ensure_adapter().get_test_case(test_case_id)

    async def update_test_case(self, test_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = f"/testcases/{test_id}"
        try:
            return await self._request("PUT", endpoint, json=updates)
        except Exception as e:
            logger.exception(f"Failed to update test case {test_id}: {e}")
            return {}

    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        return await self._ensure_adapter().get_test_cycle(cycle_key)

    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        return await self._ensure_adapter().get_test_executions(test_case_key)

    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        return await self._ensure_adapter().link_test_to_issue(test_case_key, issue_key)

    async def link_cycle_to_issue(self, cycle_key: str, issue_id: str) -> bool:
        return await self._ensure_adapter().link_cycle_to_issue(cycle_key, issue_id)

    async def link_cycle_to_weburl(self, cycle_key: str, url: str, description: str = "") -> bool:
        return await self._ensure_adapter().link_cycle_to_weburl(cycle_key, url, description)

    def add_pr_weblink(self, cycle_key: str, pr_url: str) -> bool:
        """Sync helper: add a GitHub PR URL as a web link on a Zephyr test cycle."""
        if not cycle_key or not pr_url:
            logger.warning("add_pr_weblink called without cycle_key or pr_url — skipping")
            return False

        if self.dry_run:
            logger.info(f"[dry-run] Would add weblink {pr_url} to cycle {cycle_key}")
            return True

        description = f"GitHub {pr_url.rstrip('/').split('/')[-1]}"

        async def _run():
            try:
                return await self.link_cycle_to_weburl(cycle_key, pr_url, description)
            finally:
                await self.close()

        return _run_async_safely(lambda: _run())

    # ------------------------------------------------------------------
    # Pipeline entry point
    # ------------------------------------------------------------------

    @staticmethod
    def _to_zephyr_payload(tc: Dict[str, Any], issue_key: str) -> Dict[str, Any]:
        raw_p = str(tc.get("priority", "P2")).upper()
        priority_map = {"P1": "High", "P2": "Medium", "P3": "Low"}
        zephyr_priority = priority_map.get(raw_p, "Medium")
        return {
            "name": tc.get("title", f"Test for {issue_key}"),
            "description": tc.get("description", ""),
            "priority": zephyr_priority,
            "steps": [
                {
                    "action": step.get("action", ""),
                    "expected": step.get("expected_result", ""),
                }
                for step in tc.get("steps", [])
            ],
            "precondition": "\n".join(tc.get("preconditions", [])),
        }

    async def _async_publish_live(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
        issue_id: Optional[str] = None,
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        await self.connect()
        cycle_name = f"Prism auto-tests — {issue_key}"
        cycle = await self.create_test_cycle(
            name=cycle_name, sprint_id=sprint_id, sprint_name=sprint_name
        )
        logger.info(f"Created cycle response: {cycle}")
        cycle_key = cycle.get("key") or cycle.get("id") or cycle.get("cycleKey")
        logger.info(f"Using cycle key: {cycle_key}")

        if cycle_key and not (issue_key.startswith("PR-") or issue_key.startswith("SPEC-")):
            linked = await self.link_cycle_to_issue(cycle_key, issue_id or "")
            logger.info(f"Cycle {cycle_key} linked to {issue_key} (id={issue_id}): {linked}")

        results: List[Dict[str, Any]] = []

        for tc in test_cases:
            zephyr_tc_payload = self._to_zephyr_payload(tc, issue_key)
            logger.info(f"Publishing test case: {zephyr_tc_payload.get('name', '')[:80]}")
            created_tc = await self.create_test_case(issue_key=issue_key, test_case=zephyr_tc_payload)
            test_case_key = created_tc.get("key", "UNKNOWN")
            logger.info(f"Test case created: {test_case_key}")

            execution = await self.create_test_execution(
                test_case_key=test_case_key,
                cycle_key=cycle_key,
                status="Not Executed",
            )
            execution_id = execution.get("id", "")
            logger.info(f"Execution created (Not Executed) for {test_case_key}: {execution_id}")

            # NOTE: We intentionally do NOT call update_test_execution here
            # anymore. Execution status must only be set once the generated
            # automation has actually run (see Track B: real execution sync
            # in pipeline_runner.py / TestExecutor). Hardcoding "Pass" at
            # publish time (the previous behavior) misrepresented untested
            # code as passing.

            results.append({
                "issue_key": issue_key,
                "test_case_id": tc.get("id"),
                "test_case_key": test_case_key,
                "cycle_key": cycle_key,
                "execution_id": execution_id,
                "status": "live",
                "zephyr_test_case": created_tc,
                "zephyr_execution": execution,
            })

        return results

    def publish_test_cases(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
        issue_id: Optional[str] = None,
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Publish test cases to Zephyr. Raises on failure."""
        if not test_cases:
            return []

        if self.dry_run:
            logger.info("Zephyr dry-run mode: generating mock demo publish results")
            results = []
            for idx, tc in enumerate(test_cases, start=1):
                results.append({
                    "issue_key": issue_key,
                    "test_case_id": tc.get("id"),
                    "test_case_key": f"ZT-T{idx}",
                    "cycle_key": "ZT-C1",
                    "execution_id": f"ZT-E{idx}",
                    "status": "demo",
                    "zephyr_test_case": {"key": f"ZT-T{idx}"},
                    "zephyr_execution": {"statusName": "Not Executed"},
                })
            return results

        async def _run():
            try:
                return await self._async_publish_live(
                    issue_key, test_cases, issue_id, sprint_id=sprint_id, sprint_name=sprint_name
                )
            finally:
                await self.close()
        return _run_async_safely(lambda: _run())

    async def publish_test_cases_async(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
        issue_id: Optional[str] = None,
        sprint_id: Optional[int] = None,
        sprint_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Async version of publish_test_cases."""
        if self.dry_run:
            results = []
            for idx, tc in enumerate(test_cases, start=1):
                results.append({
                    "issue_key": issue_key,
                    "test_case_id": tc.get("id"),
                    "test_case_key": f"ZT-T{idx}",
                    "cycle_key": "ZT-C1",
                    "execution_id": f"ZT-E{idx}",
                    "status": "demo",
                    "zephyr_test_case": {"key": f"ZT-T{idx}"},
                    "zephyr_execution": {"statusName": "Not Executed"},
                })
            return results
        return await self._async_publish_live(
            issue_key, test_cases, issue_id, sprint_id=sprint_id, sprint_name=sprint_name
        )