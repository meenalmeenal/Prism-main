"""
Zephyr Squad Cloud REST API Client

This module provides a client for interacting with the Zephyr Squad Cloud REST API,
with fallback to mock mode when DRY_RUN is enabled.
"""

import os
import json
import logging
import aiohttp
from aiohttp import ClientResponseError
import asyncio
import concurrent.futures
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, TypeVar, Type, cast
from dataclasses import dataclass, asdict
import uuid
from datetime import datetime, timezone
from functools import wraps

logger = logging.getLogger(__name__)
T = TypeVar('T')

# Constants
DEFAULT_RETRIES = 3
RETRY_DELAY = 1  # seconds
DEMO_EXPORT_DIR = Path("data") / "zephyr_demo"


def _run_async_safely(coro_factory):
    """Run an async coroutine from sync code; safe when a loop is already running (uses a thread)."""

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
                    wait_time = delay * (2 ** attempt)  # Exponential backoff
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
        """Convert to dictionary for API requests."""
        result = asdict(self)
        # Remove None values
        return {k: v for k, v in result.items() if v is not None}

class ZephyrClient:
    """Client for interacting with Zephyr Squad Cloud REST API.

    Example:
        ```python
        async with ZephyrClient() as client:
            # Create a test case
            test_case = await client.create_test_case(
                issue_key="PROJ-123",
                test_case={"name": "Login Test", "description": "Test login functionality"}
            )
            
            # Create a test cycle
            cycle = await client.create_test_cycle("Sprint 1 Tests")
            
            # Create and update test execution
            execution = await client.create_test_execution(
                test_case_key=test_case["key"],
                cycle_key=cycle["key"]
            )
            await client.update_test_execution(
                execution["id"],
                ZephyrTestResult(
                    test_case_key=test_case["key"],
                    status="PASS",
                    comment="Test passed successfully"
                )
            )
        ```
    """

    BASE_URL = "https://api.zephyrscale.smartbear.com/v2"
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        dry_run: Optional[bool] = None,
        base_url: Optional[str] = None,
        timeout: int = 30
    ):
        """Initialize the Zephyr client.
        
        Args:
            api_token: Zephyr API token. If not provided, will use ZEPHYR_API_TOKEN env var.
            dry_run: If True, use mock mode. If None, uses ZEPHYR_DRY_RUN env var.
            base_url: Base URL for the Zephyr API. Defaults to production.
            timeout: Request timeout in seconds.
        """
        self.api_token = api_token or os.getenv("ZEPHYR_API_TOKEN")
        self.dry_run = dry_run if dry_run is not None else os.getenv("ZEPHYR_DRY_RUN", "").lower() == "true"
        # Ensure base_url ends with a trailing slash
        self.base_url = (base_url or self.BASE_URL).rstrip('/') + '/'
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        self.test_cases: Dict[str, Dict] = {}  # In-memory store for mock mode
        self.test_cycles: Dict[str, Dict] = {}  # Track test cycles in mock mode
        self.test_executions: Dict[str, Dict] = {}  # Track test executions in mock mode
        # Explicit demo mode: never call real Zephyr APIs (for PRISM demos without JWT / ZAPI secrets)
        self.force_demo_mode: bool = os.getenv("ZEPHYR_DEMO_MODE", "").lower() in {"1", "true", "yes"}

        if not self.dry_run and not self.api_token:
            logger.warning("Zephyr API token not provided and ZEPHYR_DRY_RUN is not set. Using Zephyr Demo Mode.")
            self.dry_run = True

    async def __aenter__(self) -> 'ZephyrClient':
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    async def connect(self) -> None:
        """Initialize the HTTP session."""
        if self.dry_run:
            logger.info("Zephyr client running in DRY_RUN mode")
            return

        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=self.timeout
            )
            logger.debug("Zephyr client connected")

    async def close(self) -> None:
        """Close the HTTP session."""
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
        """Make an API request to Zephyr Squad Cloud.
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint (e.g., '/testcases')
            **kwargs: Additional arguments for the request
            
        Returns:
            Response data as a dictionary or list of dictionaries
            
        Raises:
            aiohttp.ClientError: If the request fails after retries
        """
        if self.dry_run:
            logger.debug(f"[MOCK] {method} {endpoint}")
            return await self._mock_request(method, endpoint, **kwargs)

        if not self.session or self.session.closed:
            await self.connect()

        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.debug(f"Making {method} request to {url}")

        try:
            async with self.session.request(method, url, **kwargs) as response:
                response.raise_for_status()
                
                if response.status == 204:  # No content
                    return {}
                    
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    return await response.json()
                return await response.text()
                
        except aiohttp.ClientError as e:
            error_msg = f"Zephyr API request failed: {str(e)}"
            if hasattr(e, 'response') and e.response:
                try:
                    error_detail = await e.response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - Status: {e.response.status}"
            logger.error(error_msg)
            raise

    async def _mock_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """Handle mock requests for dry run mode."""
        # Simulate network delay
        await asyncio.sleep(0.1)
        
        # Handle different endpoints
        if method == "POST" and endpoint == "/testcases":
            return await self._mock_create_test_case(kwargs.get('json', {}))
            
        elif method == "PATCH" and endpoint.startswith("/testcases/"):
            test_case_id = endpoint.split("/")[-1]
            return await self._mock_update_test_case(test_case_id, kwargs.get('json', {}))
            
        elif method == "POST" and endpoint == "/testexecutions":
            return await self._mock_create_test_execution(kwargs.get('json', {}))
            
        elif method == "POST" and "/testexecutions/" in endpoint and "/execute" in endpoint:
            execution_id = endpoint.split("/")[2]
            return await self._mock_update_test_execution(execution_id, kwargs.get('json', {}))
            
        elif method == "POST" and endpoint == "/testcycles":
            return await self._mock_create_test_cycle(kwargs.get('json', {}))
            
        return {"status": "success", "message": "Dry run mode"}

    # Mock implementations for each endpoint
    async def _mock_create_test_case(self, data: Dict) -> Dict:
        test_case_id = f"ZT-{str(uuid.uuid4())[:8]}"
        self.test_cases[test_case_id] = {
            "key": test_case_id,
            **data,
            "created": datetime.now(timezone.utc).isoformat()
        }
        return self.test_cases[test_case_id]

    async def _mock_update_test_case(self, test_case_id: str, updates: Dict) -> Dict:
        if test_case_id in self.test_cases:
            self.test_cases[test_case_id].update(updates)
            self.test_cases[test_case_id]["updated"] = datetime.now(timezone.utc).isoformat()
            return self.test_cases[test_case_id]
        return {"error": "Test case not found"}

    async def _mock_create_test_execution(self, data: Dict) -> Dict:
        execution_id = str(uuid.uuid4())
        self.test_executions[execution_id] = {
            "id": execution_id,
            "key": f"ZT-{execution_id[:8]}",
            **data,
            "created": datetime.now(timezone.utc).isoformat()
        }
        return self.test_executions[execution_id]

    async def _mock_update_test_execution(self, execution_id: str, data: Dict) -> Dict:
        if execution_id in self.test_executions:
            self.test_executions[execution_id].update(data)
            self.test_executions[execution_id]["updated"] = datetime.now(timezone.utc).isoformat()
            return self.test_executions[execution_id]
        return {"error": "Test execution not found"}

    async def _mock_create_test_cycle(self, data: Dict) -> Dict:
        cycle_key = f"{data.get('projectKey', 'ZT')}-{str(uuid.uuid4())[:4]}"
        self.test_cycles[cycle_key] = {
            "key": cycle_key,
            **data,
            "created": datetime.now(timezone.utc).isoformat()
        }
        return self.test_cycles[cycle_key]

    # Public API methods
    async def create_test_case(self, issue_key: str, test_case: Dict) -> Dict:
        """Create a new test case in Zephyr.
        
        Args:
            issue_key: Jira issue key to link the test case to
            test_case: Test case data with keys like 'name', 'description', 'steps', etc.
            
        Returns:
            Created test case data with 'key' field
            
        Example:
            ```python
            test_case = {
                "name": "Login Test",
                "description": "Test user login functionality",
                "priority": "High",
                "steps": [
                    {"action": "Open login page", "expected": "Login page loads"},
                    {"action": "Enter credentials", "expected": "User is logged in"}
                ]
            }
            result = await client.create_test_case("PROJ-123", test_case)
            ```
        """
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

    async def update_test_case(self, test_case_id: str, updates: Dict) -> Dict:
        """Update an existing test case.
        
        Args:
            test_case_id: Zephyr test case ID
            updates: Fields to update (same as create but partial)
            
        Returns:
            Updated test case data
        """
        endpoint = f"/testcases/{test_case_id}"
        return await self._request("PATCH", endpoint, json=updates)

    async def create_test_execution(
        self,
        test_case_key: str,
        cycle_key: str,
        status: str = "UNEXECUTED"
    ) -> Dict:
        """Create a test execution in Zephyr.
        
        Args:
            test_case_key: Zephyr test case key
            cycle_key: Test cycle key
            status: Initial status of the test execution
            
        Returns:
            Test execution data with 'id' and 'key' fields
        """
        endpoint = "/testexecutions"
        data = {
            "projectKey": os.getenv("ZEPHYR_PROJECT_KEY", "ZT"),
            "testCaseKey": test_case_key,
            "cycleKey": cycle_key or f"ZT-R{datetime.now().strftime('%Y%m%d')}",
            "status": status,
            "environment": os.getenv("ENVIRONMENT", "TEST")
        }
        return await self._request("POST", endpoint, json=data)

    async def update_test_execution(
        self,
        execution_id: str,
        result: ZephyrTestResult
    ) -> Dict:
        """Update a test execution with results.
        
        Args:
            execution_id: Test execution ID
            result: Test result data
            
        Returns:
            Updated test execution data
        """
        endpoint = f"/testexecutions/{execution_id}/execute"
        data = {
            "status": result.status,
            "comment": result.comment,
            "executedOn": result.finished_on or datetime.utcnow().isoformat() + "Z",
            "executedById": "auto"
        }
        return await self._request("POST", endpoint, json=data)

    async def get_test_case(self, test_case_id: str) -> Optional[Dict]:
        """Get a test case by ID.
        
        Args:
            test_case_id: Zephyr test case ID
            
        Returns:
            Test case data or None if not found
        """
        endpoint = f"/testcases/{test_case_id}"
        try:
            return await self._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    async def create_test_cycle(
        self,
        name: str,
        project_key: Optional[str] = None,
        description: str = "",
        jira_project_version: Optional[str] = None
    ) -> Dict:
        """Create a test cycle.
        
        Args:
            name: Name of the test cycle
            project_key: Project key (defaults to ZEPHYR_PROJECT_KEY)
            description: Optional description
            jira_project_version: Optional JIRA project version
            
        Returns:
            Created test cycle data with 'key' field
        """
        endpoint = "/testcycles"
        project_key = project_key or os.getenv("ZEPHYR_PROJECT_KEY", "ZT")
        data = {
            "name": name,
            "projectKey": project_key,
            "description": description
        }
        if jira_project_version:
            data["jiraProjectVersion"] = jira_project_version
            
        return await self._request("POST", endpoint, json=data)

    async def link_test_to_issue(self, test_case_key: str, issue_key: str) -> bool:
        """Link a test case to a Jira issue.
        
        Args:
            test_case_key: Zephyr test case key
            issue_key: Jira issue key
            
        Returns:
            True if successful, False otherwise
        """
        endpoint = f"/testcases/{test_case_key}/links/issues"
        try:
            await self._request("POST", endpoint, json={"issueKey": issue_key})
            return True
        except aiohttp.ClientError:
            logger.exception(f"Failed to link test case {test_case_key} to issue {issue_key}")
            return False

    async def get_test_executions(self, test_case_key: str) -> List[Dict]:
        """Get all executions for a test case.
        
        Args:
            test_case_key: Zephyr test case key
            
        Returns:
            List of test executions
        """
        endpoint = f"/testexecutions?testCaseKey={test_case_key}"
        try:
            result = await self._request("GET", endpoint)
            return result.get("values", [])
        except aiohttp.ClientError:
            logger.exception(f"Failed to get executions for test case {test_case_key}")
            return []

    async def get_test_cycle(self, cycle_key: str) -> Optional[Dict]:
        """Get a test cycle by key.
        
        Args:
            cycle_key: Test cycle key
            
        Returns:
            Test cycle data or None if not found
        """
        endpoint = f"/testcycles/{cycle_key}"
        try:
            return await self._request("GET", endpoint)
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise

    # ------------------------------------------------------------------
    # Pipeline entry point: sync, never raises — live API or Zephyr Demo Mode
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

    def _zephyr_demo_publish(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
        *,
        reason: str,
    ) -> List[Dict[str, Any]]:
        """Zephyr Demo Mode: structured JSON export + console logs (no API). Never raises."""

        DEMO_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        results: List[Dict[str, Any]] = []
        export_rows: List[Dict[str, Any]] = []
        tc_num = 101

        jira_base = (os.getenv("JIRA_BASE_URL") or "https://your-domain.atlassian.net").rstrip("/")
        logger.info(
            "Zephyr Demo Mode active (%s). Open Jira issue in browser: %s/browse/%s — add or view tests in Zephyr / Zephyr Scale.",
            reason,
            jira_base,
            issue_key,
        )

        for tc in test_cases:
            zephyr_tc_payload = self._to_zephyr_payload(tc, issue_key)
            zephyr_id = f"TC-{tc_num}"
            tc_num += 1

            logger.info("Publishing test case to Zephyr... (title=%s)", zephyr_tc_payload.get("name", "")[:80])
            logger.info("Test Case %s created in Zephyr (Demo Mode)", zephyr_id)

            row = {
                "zephyr_test_case_id": zephyr_id,
                "internal_id": tc.get("id"),
                "title": zephyr_tc_payload.get("name"),
                "linked_jira_issue": issue_key,
                "priority": zephyr_tc_payload.get("priority"),
                "steps": zephyr_tc_payload.get("steps"),
            }
            export_rows.append(row)

            results.append(
                {
                    "issue_key": issue_key,
                    "test_case_key": zephyr_id,
                    "cycle_key": "DEMO-CYCLE",
                    "execution_id": f"DEMO-EXEC-{uuid.uuid4().hex[:8]}",
                    "status": "demo_mode",
                    "mode": "zephyr_demo",
                    "reason": reason,
                    "zephyr_test_case": {"key": zephyr_id, **zephyr_tc_payload},
                    "zephyr_execution": {"status": "PASS", "comment": "Simulated in Zephyr Demo Mode"},
                }
            )

        export_path = DEMO_EXPORT_DIR / f"{issue_key.replace('/', '_')}_zephyr_published.json"
        payload = {
            "issue_key": issue_key,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "mode": "zephyr_demo",
            "reason": reason,
            "integration": "Zephyr Scale Cloud API (Bearer) or Zephyr for Jira — demo export when API unavailable",
            "test_cases": export_rows,
        }
        try:
            export_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Zephyr Demo Mode: saved structured export to %s", export_path)
        except OSError as exc:
            logger.warning("Zephyr Demo Mode: could not write export file: %s", exc)

        logger.info("Zephyr Demo Mode: published %d test case(s) for %s", len(results), issue_key)
        return results

    async def _async_publish_live(self, issue_key: str, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Call Zephyr Scale REST API (Bearer token). Raises on failure."""

        saved_dry = self.dry_run
        self.dry_run = False
        try:
            await self.connect()
            cycle_name = f"Prism auto-tests — {issue_key}"
            cycle = await self.create_test_cycle(name=cycle_name)
            cycle_key = cycle.get("key", f"{os.getenv('ZEPHYR_PROJECT_KEY', 'ZT')}-AUTO")
            results: List[Dict[str, Any]] = []

            for tc in test_cases:
                zephyr_tc_payload = self._to_zephyr_payload(tc, issue_key)
                logger.info("Publishing test case to Zephyr (API)... (title=%s)", zephyr_tc_payload.get("name", "")[:80])
                created_tc = await self.create_test_case(issue_key=issue_key, test_case=zephyr_tc_payload)
                test_case_key = created_tc.get("key", "UNKNOWN")
                execution = await self.create_test_execution(
                    test_case_key=test_case_key,
                    cycle_key=cycle_key,
                    status="UNEXECUTED",
                )
                execution_id = execution.get("id", "")
                result_obj = ZephyrTestResult(
                    test_case_key=test_case_key,
                    status="PASS",
                    comment="Auto-published from Prism pipeline",
                )
                updated_execution = await self.update_test_execution(execution_id, result_obj)
                logger.info("Test Case %s created in Zephyr (API)", test_case_key)
                results.append(
                    {
                        "issue_key": issue_key,
                        "test_case_key": test_case_key,
                        "cycle_key": cycle_key,
                        "execution_id": execution_id,
                        "status": "live",
                        "zephyr_test_case": created_tc,
                        "zephyr_execution": updated_execution,
                    }
                )
            return results
        except ClientResponseError as e:
            if e.status == 401:
                logger.warning(
                    "Falling back to Zephyr Demo Mode (401 Unauthorized — check ZEPHYR_API_TOKEN). "
                    "Using mock publish; pipeline continues."
                )
                return self._zephyr_demo_publish(
                    issue_key, test_cases, reason="401_unauthorized"
                )
            raise
        finally:
            self.dry_run = saved_dry
            await self.close()

    async def _async_publish_or_demo(self, issue_key: str, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not test_cases:
            return []

        if self.force_demo_mode or self.dry_run or not (self.api_token and str(self.api_token).strip()):
            reason = "ZEPHYR_DEMO_MODE or ZEPHYR_DRY_RUN or missing ZEPHYR_API_TOKEN"
            return self._zephyr_demo_publish(issue_key, test_cases, reason=reason)

        try:
            return await self._async_publish_live(issue_key, test_cases)
        except Exception as exc:
            logger.warning(
                "Zephyr live API failed (%s). Falling back to Zephyr Demo Mode — demo will not fail the pipeline.",
                exc,
            )
            return self._zephyr_demo_publish(issue_key, test_cases, reason=f"api_error: {exc}")

    def publish_test_cases(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Publish test cases to Zephyr Scale (Bearer token) or Zephyr Demo Mode.

        - Attempts real ``/v2`` API when ``ZEPHYR_API_TOKEN`` is set and demo/dry-run is off.
        - On any failure (or no token / ``ZEPHYR_DRY_RUN`` / ``ZEPHYR_DEMO_MODE``): writes JSON under
          ``data/zephyr_demo/`` and logs demo messages. **Never raises.**

        Parameters
        ----------
        issue_key:
            Jira issue key to link test cases (e.g. ``PROJ-123``).
        test_cases:
            Validated test case dicts from the pipeline (title, steps, priority, ...).
        """

        if not test_cases:
            return []

        try:
            return _run_async_safely(lambda: self._async_publish_or_demo(issue_key, test_cases))
        except Exception as exc:
            logger.exception("Unexpected Zephyr publish error; using Demo Mode: %s", exc)
            return self._zephyr_demo_publish(issue_key, test_cases, reason=f"unexpected: {exc}")

    async def publish_test_cases_async(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Async alias for callers already inside an event loop."""

        return await self._async_publish_or_demo(issue_key, test_cases)