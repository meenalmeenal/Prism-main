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
            Execution results from TestExecutor
        """
        entry = {
            "issue_key": issue_key,
            "timestamp": datetime.now().isoformat(),
            "total_tests": execution_results.get("total_tests", 0),
            "passed": execution_results.get("passed", 0),
            "failed": execution_results.get("failed", 0),
            "skipped": execution_results.get("skipped", 0),
            "duration_seconds": execution_results.get("duration_seconds", 0),
            "pass_rate": (
                execution_results.get("passed", 0) / execution_results.get("total_tests", 1) * 100
                if execution_results.get("total_tests", 0) > 0
                else 0
            ),
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

    def get_flaky_test_report(self) -> List[Dict[str, Any]]:
        """Identify flaky tests from execution history."""
        test_stability = defaultdict(list)

        for execution in self._db.get("executions", []):
            issue_key = execution.get("issue_key", "unknown")
            for result in execution.get("execution_results", {}).get("test_results", []):
                test_file = result.get("test_file", "unknown")
                status = result.get("status", "unknown")
                test_stability[f"{issue_key}:{test_file}"].append(status)

        flaky_tests = []
        for test_id, statuses in test_stability.items():
            if len(statuses) >= 3:  # Need multiple runs to determine flakiness
                pass_count = statuses.count("passed")
                fail_count = statuses.count("failed")
                if pass_count > 0 and fail_count > 0:
                    flakiness_rate = (min(pass_count, fail_count) / len(statuses)) * 100
                    flaky_tests.append({
                        "test_id": test_id,
                        "total_runs": len(statuses),
                        "pass_count": pass_count,
                        "fail_count": fail_count,
                        "flakiness_rate": round(flakiness_rate, 2),
                    })

        return sorted(flaky_tests, key=lambda x: x["flakiness_rate"], reverse=True)

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

