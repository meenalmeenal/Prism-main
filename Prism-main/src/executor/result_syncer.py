"""Result syncing module.

Syncs test execution results back to Zephyr executions.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime

from dotenv import load_dotenv
from pathlib import Path

load_dotenv()
logger = logging.getLogger(__name__)


class ResultSyncer:
    """Syncs test execution results to Zephyr."""

    def __init__(self):
        """Initialize the result syncer."""
        self.base_url = os.getenv("ZEPHYR_BASE_URL", "https://api.zephyrscale.smartbear.com")
        self.api_token = os.getenv("ZEPHYR_API_TOKEN")
        self._requests = None

        if self.api_token:
            try:
                import requests
                self._requests = requests
                logger.info("ResultSyncer initialized with live API")
            except ImportError:
                logger.warning("requests not available, ResultSyncer in mock mode")
        else:
            logger.info("ResultSyncer initialized in mock mode (no API token)")

    def sync_execution_results(
        self,
        execution_results: Dict[str, Any],
        test_case_mapping: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Sync execution results to Zephyr.

        Parameters
        ----------
        execution_results: Dict[str, Any]
            Execution results from TestExecutor
        test_case_mapping: Dict[str, str]
            Mapping of test file names to Zephyr test case keys

        Returns
        -------
        List[Dict[str, Any]]
            Sync results for each test case
        """
        logger.info(f"Syncing {len(execution_results.get('test_results', []))} test results to Zephyr")

        if not self._requests or not self.api_token:
            return self._mock_sync(execution_results, test_case_mapping)

        sync_results = []

        for test_result in execution_results.get("test_results", []):
            test_file = test_result.get("test_file", "")
            test_name = Path(test_file).stem if test_file else "unknown"

            # Find Zephyr test case key
            zephyr_key = test_case_mapping.get(test_name) or test_case_mapping.get(test_file)

            if not zephyr_key:
                logger.warning(f"No Zephyr key found for {test_name}, skipping sync")
                continue

            try:
                sync_result = self._create_execution(zephyr_key, test_result, execution_results)
                sync_results.append(sync_result)
            except Exception as exc:
                logger.error(f"Failed to sync result for {zephyr_key}: {exc}")
                sync_results.append({
                    "zephyr_key": zephyr_key,
                    "status": "failed",
                    "error": str(exc),
                })

        logger.info(f"Synced {len([r for r in sync_results if r.get('status') == 'synced'])}/{len(sync_results)} results")
        return sync_results

    def _create_execution(
        self,
        zephyr_key: str,
        test_result: Dict[str, Any],
        execution_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a test execution in Zephyr."""
        status = test_result.get("status", "unknown")
        zephyr_status = "PASS" if status == "passed" else "FAIL" if status == "failed" else "UNEXECUTED"

        # Build execution payload
        payload = {
            "testCaseKey": zephyr_key,
            "statusName": zephyr_status,
            "executionTime": int(test_result.get("duration_seconds", 0) * 1000),  # milliseconds
            "comment": f"Auto-executed via Prism pipeline\nStatus: {status}\nDuration: {test_result.get('duration_seconds', 0):.2f}s",
        }

        if status == "failed" and test_result.get("error"):
            payload["comment"] += f"\nError: {test_result['error']}"

        url = f"{self.base_url.rstrip('/')}/v2/testexecutions"
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        response = self._requests.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()

        execution_data = response.json()

        logger.info(f"Created Zephyr execution for {zephyr_key}: {zephyr_status}")

        return {
            "zephyr_key": zephyr_key,
            "execution_key": execution_data.get("key") or execution_data.get("id"),
            "status": "synced",
            "zephyr_status": zephyr_status,
        }

    def _mock_sync(
        self,
        execution_results: Dict[str, Any],
        test_case_mapping: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        """Mock sync for offline/demo mode."""
        logger.info("Mock syncing execution results (no API token)")

        sync_results = []

        for test_result in execution_results.get("test_results", []):
            test_file = test_result.get("test_file", "")
            test_name = Path(test_file).stem if test_file else "unknown"
            zephyr_key = test_case_mapping.get(test_name) or f"MOCK-{test_name}"

            status = test_result.get("status", "unknown")
            zephyr_status = "PASS" if status == "passed" else "FAIL" if status == "failed" else "UNEXECUTED"

            sync_results.append({
                "zephyr_key": zephyr_key,
                "execution_key": f"MOCK-EXEC-{test_name}",
                "status": "mock_synced",
                "zephyr_status": zephyr_status,
            })

        return sync_results


# Import Path here to avoid circular import
