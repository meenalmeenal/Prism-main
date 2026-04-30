"""
Zephyr Essential Cloud REST API Client
"""

import os
import logging
import aiohttp
from aiohttp import ClientResponseError
import asyncio
import concurrent.futures
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


class ZephyrClient:
    """Client for interacting with Zephyr Essential Cloud REST API."""

    BASE_URL = "https://prod-api.zephyr4jiracloud.com/v2"

    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30
    ):
        self.api_token = api_token or os.getenv("ZEPHYR_API_TOKEN")
        self.base_url = (base_url or os.getenv("ZEPHYR_BASE_URL") or self.BASE_URL).rstrip('/') + '/'
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None

        if not self.api_token:
            raise ValueError("ZEPHYR_API_TOKEN is required but not set.")

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
    # Public API methods
    # ------------------------------------------------------------------

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
            },
            "issueLinks": [issue_key]
        }
        return await self._request("POST", endpoint, json=data)

    async def create_test_cycle(
        self,
        name: str,
        project_key: Optional[str] = None,
        description: str = "",
    ) -> Dict:
        endpoint = "/testcycles"
        project_key = project_key or os.getenv("ZEPHYR_PROJECT_KEY", "ZT")
        data = {
            "name": name,
            "projectKey": project_key,
            "description": description
        }
        return await self._request("POST", endpoint, json=data)

    async def create_test_execution(
        self,
        test_case_key: str,
        cycle_key: str,
        status: str = "Not Executed"
    ) -> Dict:
        endpoint = "/testexecutions"
        data = {
            "projectKey": os.getenv("ZEPHYR_PROJECT_KEY", "ZT"),
            "testCaseKey": test_case_key,
            "testCycleKey": cycle_key,
            "statusName": status
        }
        logger.info(f"create_test_execution payload: {data}")
        return await self._request("POST", endpoint, json=data)

    async def update_test_execution(
        self,
        execution_id: str,
        result: ZephyrTestResult
    ) -> Dict:
        endpoint = f"/testexecutions/{execution_id}"
        data = {
            "statusName": result.status,
            "comment": result.comment,
            "executedOn": result.finished_on or datetime.now(timezone.utc).isoformat()
        }
        return await self._request("PUT", endpoint, json=data)

    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        endpoint = f"/testcases/{test_case_id}"
        try:
            return await self._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        endpoint = f"/testcycles/{cycle_key}"
        try:
            return await self._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        endpoint = f"/testexecutions?testCaseKey={test_case_key}"
        try:
            result = await self._request("GET", endpoint)
            return result.get("values", [])
        except aiohttp.ClientError:
            logger.exception(f"Failed to get executions for {test_case_key}")
            return []

    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        endpoint = f"/testcases/{test_case_key}/links/issues"
        try:
            await self._request("POST", endpoint, json={"issueKey": issue_key})
            return True
        except aiohttp.ClientError:
            logger.exception(f"Failed to link {test_case_key} to {issue_key}")
            return False

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

    async def _async_publish_live(self, issue_key: str, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        await self.connect()
        cycle_name = f"Prism auto-tests — {issue_key}"
        cycle = await self.create_test_cycle(name=cycle_name)
        logger.info(f"Created cycle response: {cycle}")
        cycle_key = cycle.get("key") or cycle.get("id") or cycle.get("cycleKey")
        logger.info(f"Using cycle key: {cycle_key}")
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
            )
            execution_id = execution.get("id", "")
            logger.info(f"Execution created: {execution_id}")

            result_obj = ZephyrTestResult(
                test_case_key=test_case_key,
                status="Pass",
                comment="Auto-published from Prism pipeline",
            )
            updated_execution = await self.update_test_execution(execution_id, result_obj)
            logger.info(f"Execution updated for {test_case_key}")

            results.append({
                "issue_key": issue_key,
                "test_case_key": test_case_key,
                "cycle_key": cycle_key,
                "execution_id": execution_id,
                "status": "live",
                "zephyr_test_case": created_tc,
                "zephyr_execution": updated_execution,
            })

        return results

    def publish_test_cases(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Publish test cases to Zephyr Essential Cloud. Raises on failure."""
        if not test_cases:
            return []

        async def _run():
            try:
                return await self._async_publish_live(issue_key, test_cases)
            finally:
                await self.close()

        return _run_async_safely(lambda: _run())

    async def publish_test_cases_async(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Async version of publish_test_cases."""
        return await self._async_publish_live(issue_key, test_cases)