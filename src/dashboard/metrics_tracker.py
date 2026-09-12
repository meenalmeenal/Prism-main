"""Metrics tracker for test coverage and execution statistics."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MetricsTracker:
    """Tracks metrics for test coverage, execution, and quality."""

    def __init__(self, metrics_db_path: str = "data/metrics_db.json"):
        """Initialize the metrics tracker.

        Parameters
        ----------
        metrics_db_path: str
            Path to store metrics data
        """
        self.metrics_db_path = Path(metrics_db_path)
        self.metrics_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_metrics_db()

    def record_test_generation(
        self,
        issue_key: str,
        test_cases: List[Dict[str, Any]],
        generation_time: float,
    ) -> None:
        """Record test generation metrics.

        Parameters
        ----------
        issue_key: str
            Jira issue key
        test_cases: List[Dict[str, Any]]
            Generated test cases
        generation_time: float
            Time taken to generate tests in seconds
        """
        entry = {
            "issue_key": issue_key,
            "timestamp": datetime.now().isoformat(),
            "test_count": len(test_cases),
            "generation_time_seconds": generation_time,
            "test_types": self._count_test_types(test_cases),
            "priorities": self._count_priorities(test_cases),
        }

        self._db["generations"].append(entry)
        self._save_metrics_db()

    def record_execution_metrics(
        self,
        issue_key: str,
        execution_results: Dict[str, Any],
    ) -> None:
        """Record execution metrics.

        Parameters
        ----------
        issue_key: str
            Jira issue key
        execution_results: Dict[str, Any]
            Execution results from TestExecutor containing per_test
        """
        raw_per_test = execution_results.get("per_test")
        if raw_per_test is not None:
            per_test = [
                {
                    "test_case_id": str(t.get("test_case_id", "unknown")),
                    "title": str(t.get("title", "Test Case")),
                    "status": str(t.get("status", "Not Executed")),
                    "duration_ms": int(t.get("duration_ms", 0)),
                }
                for t in raw_per_test
            ]
        else:
            per_test = []
            for tr in execution_results.get("test_results", []):
                st = tr.get("status", "")
                norm_st = "Pass" if st == "passed" else ("Fail" if st in {"failed", "error"} else (st or "Not Executed"))
                per_test.append({
                    "test_case_id": str(tr.get("test_name", tr.get("test_file", "unknown"))),
                    "title": str(tr.get("test_name", "Test Case")),
                    "status": norm_st,
                    "duration_ms": int(tr.get("duration_ms", 0)),
                })

        passed_count = execution_results.get("passed", sum(1 for t in per_test if t.get("status") in {"Pass", "passed"}))
        failed_count = execution_results.get("failed", sum(1 for t in per_test if t.get("status") in {"Fail", "failed", "error"}))
        skipped_count = execution_results.get("skipped", sum(1 for t in per_test if t.get("status") in {"Skip", "skipped"}))
        total_count = execution_results.get("total_tests", len(per_test))

        entry = {
            "issue_key": issue_key,
            "timestamp": datetime.now().isoformat(),
            "total_tests": total_count,
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "duration_seconds": execution_results.get("duration_seconds", 0),
            "pass_rate": (
                passed_count / total_count * 100
                if total_count > 0
                else 0
            ),
            "per_test": per_test,
        }

        self._db["executions"].append(entry)
        self._save_metrics_db()

    def get_coverage_metrics(self, days: int = 30) -> Dict[str, Any]:
        """Get coverage metrics for the last N days.

        Parameters
        ----------
        days: int
            Number of days to look back

        Returns
        -------
        Dict[str, Any]
            Coverage metrics
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        recent_generations = [
            g for g in self._db.get("generations", [])
            if datetime.fromisoformat(g["timestamp"]) >= cutoff_date
        ]

        recent_executions = [
            e for e in self._db.get("executions", [])
            if datetime.fromisoformat(e["timestamp"]) >= cutoff_date
        ]

        total_tests_generated = sum(g["test_count"] for g in recent_generations)
        total_tests_executed = sum(e["total_tests"] for e in recent_executions)
        total_passed = sum(e["passed"] for e in recent_executions)
        total_failed = sum(e["failed"] for e in recent_executions)

        overall_pass_rate = (
            (total_passed / total_tests_executed * 100)
            if total_tests_executed > 0
            else 0
        )

        return {
            "period_days": days,
            "total_issues_processed": len(recent_generations),
            "total_tests_generated": total_tests_generated,
            "total_tests_executed": total_tests_executed,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "overall_pass_rate": round(overall_pass_rate, 2),
            "coverage_percentage": (
                (total_tests_executed / total_tests_generated * 100)
                if total_tests_generated > 0
                else 0
            ),
        }

    def get_flaky_test_report(self, n_runs: int = 10) -> List[Dict[str, Any]]:
        """Identify flaky tests from execution history.

        Definition:
        -----------
        A test is considered flaky if, across the last N runs (default N=10),
        it has both at least one 'Pass' and at least one 'Fail', and has >= 2 total runs.

        Note on Track B Integration:
        ----------------------------
        The `per_test` list is populated by Track B's executor. This report will be
        legitimately empty until Track B merges or execution results containing `per_test`
        are recorded.

        Parameters
        ----------
        n_runs : int
            Number of recent execution runs to analyze (default is 10).

        Returns
        -------
        List[Dict[str, Any]]
            List of flaky test dictionaries sorted by flaky_ratio descending:
            - test_case_id: str
            - title: str
            - runs: int (total execution runs considered)
            - pass_count: int (number of 'Pass' runs)
            - fail_count: int (number of 'Fail' runs)
            - flip_count: int (adjacent status changes between Pass and Fail in chronological order)
            - flaky_ratio: float (calculated as min(pass_count, fail_count) / runs)
            - avg_duration_ms: float (average duration across runs in ms)
            - last_status: str (status from the most recent run)
        """
        executions = self._db.get("executions", [])
        recent_executions = executions[-n_runs:] if len(executions) > n_runs else executions

        skipped_legacy_count = 0
        test_histories = defaultdict(list)
        test_metadata = {}

        for execution in recent_executions:
            per_test = execution.get("per_test")
            if per_test is None:
                skipped_legacy_count += 1
                continue

            for t in per_test:
                tc_id = t.get("test_case_id", "unknown")
                title = t.get("title", tc_id)
                status = str(t.get("status", "")).strip()
                duration = t.get("duration_ms", 0)

                test_metadata[tc_id] = title
                test_histories[tc_id].append({
                    "status": status,
                    "duration_ms": duration,
                })

        if skipped_legacy_count > 0:
            logger.info("Skipped %d legacy execution record(s) lacking per_test data", skipped_legacy_count)

        flaky_tests = []
        for tc_id, history in test_histories.items():
            if len(history) < 2:
                continue

            norm_statuses = [
                "Pass" if h["status"].lower() in {"pass", "passed"}
                else ("Fail" if h["status"].lower() in {"fail", "failed", "error"} else h["status"])
                for h in history
            ]

            pass_count = norm_statuses.count("Pass")
            fail_count = norm_statuses.count("Fail")

            if pass_count >= 1 and fail_count >= 1:
                flip_count = 0
                prev_status = None
                for s in norm_statuses:
                    if s in {"Pass", "Fail"}:
                        if prev_status is not None and s != prev_status:
                            flip_count += 1
                        prev_status = s

                runs = len(history)
                flaky_ratio = round(min(pass_count, fail_count) / runs, 2)
                durations = [h["duration_ms"] for h in history if isinstance(h["duration_ms"], (int, float))]
                avg_duration_ms = round(sum(durations) / len(durations), 2) if durations else 0.0
                last_status = history[-1]["status"]

                flaky_tests.append({
                    "test_case_id": tc_id,
                    "title": test_metadata.get(tc_id, tc_id),
                    "runs": runs,
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                    "flip_count": flip_count,
                    "flaky_ratio": flaky_ratio,
                    "avg_duration_ms": avg_duration_ms,
                    "last_status": last_status,
                })

        return sorted(flaky_tests, key=lambda x: (x["flaky_ratio"], x["flip_count"]), reverse=True)

    def generate_dashboard_data(self) -> Dict[str, Any]:
        """Generate comprehensive dashboard data."""
        coverage_metrics = self.get_coverage_metrics(days=30)
        flaky_tests = self.get_flaky_test_report()

        # Test type distribution
        test_type_dist = defaultdict(int)
        for gen in self._db.get("generations", []):
            for test_type, count in gen.get("test_types", {}).items():
                test_type_dist[test_type] += count

        # Priority distribution
        priority_dist = defaultdict(int)
        for gen in self._db.get("generations", []):
            for priority, count in gen.get("priorities", {}).items():
                priority_dist[priority] += count

        return {
            "coverage": coverage_metrics,
            "flaky_tests": flaky_tests,
            "test_type_distribution": dict(test_type_dist),
            "priority_distribution": dict(priority_dist),
            "last_updated": datetime.now().isoformat(),
        }

    def _count_test_types(self, test_cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count test cases by type."""
        types = defaultdict(int)
        for tc in test_cases:
            test_type = tc.get("type", "unknown")
            types[test_type] += 1
        return dict(types)

    def _count_priorities(self, test_cases: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count test cases by priority."""
        priorities = defaultdict(int)
        for tc in test_cases:
            priority = tc.get("priority", "unknown")
            priorities[priority] += 1
        return dict(priorities)

    def _load_metrics_db(self) -> None:
        """Load metrics database from disk."""
        if self.metrics_db_path.exists():
            try:
                with self.metrics_db_path.open("r", encoding="utf-8") as f:
                    self._db = json.load(f)
            except Exception as exc:
                logger.warning(f"Failed to load metrics DB: {exc}, starting fresh")
                self._db = {"generations": [], "executions": []}
        else:
            self._db = {"generations": [], "executions": []}

    def _save_metrics_db(self) -> None:
        """Save metrics database to disk."""
        try:
            with self.metrics_db_path.open("w", encoding="utf-8") as f:
                json.dump(self._db, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.error(f"Failed to save metrics DB: {exc}")

