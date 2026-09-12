import pytest
import json
from src.dashboard.metrics_tracker import MetricsTracker


def test_metrics_tracker_per_test_persistence(tmp_path):
    db_file = tmp_path / "metrics_db.json"
    tracker = MetricsTracker(metrics_db_path=str(db_file))

    per_test = [
        {"test_case_id": "ZT-1-TC-001", "title": "Valid login", "status": "Pass", "duration_ms": 120},
        {"test_case_id": "ZT-1-TC-002", "title": "Invalid password", "status": "Fail", "duration_ms": 150},
    ]

    exec_results = {
        "total_tests": 2,
        "passed": 1,
        "failed": 1,
        "skipped": 0,
        "duration_seconds": 1.2,
        "per_test": per_test,
    }

    tracker.record_execution_metrics("ZT-1", exec_results)

    # Read back with new tracker instance
    tracker2 = MetricsTracker(metrics_db_path=str(db_file))
    executions = tracker2._db.get("executions", [])
    assert len(executions) == 1
    assert executions[0]["issue_key"] == "ZT-1"
    assert executions[0]["per_test"] == per_test


def test_get_flaky_test_report_identifies_flaky_tests(tmp_path):
    db_file = tmp_path / "metrics_db.json"
    tracker = MetricsTracker(metrics_db_path=str(db_file))

    # Run 1: TC-001 Pass, TC-002 Pass
    tracker.record_execution_metrics("ZT-1", {
        "per_test": [
            {"test_case_id": "TC-001", "title": "Test 1", "status": "Pass", "duration_ms": 100},
            {"test_case_id": "TC-002", "title": "Test 2", "status": "Pass", "duration_ms": 200},
        ]
    })
    # Run 2: TC-001 Fail, TC-002 Pass
    tracker.record_execution_metrics("ZT-1", {
        "per_test": [
            {"test_case_id": "TC-001", "title": "Test 1", "status": "Fail", "duration_ms": 150},
            {"test_case_id": "TC-002", "title": "Test 2", "status": "Pass", "duration_ms": 210},
        ]
    })
    # Run 3: TC-001 Pass, TC-002 Pass
    tracker.record_execution_metrics("ZT-1", {
        "per_test": [
            {"test_case_id": "TC-001", "title": "Test 1", "status": "Pass", "duration_ms": 110},
            {"test_case_id": "TC-002", "title": "Test 2", "status": "Pass", "duration_ms": 190},
        ]
    })

    report = tracker.get_flaky_test_report(n_runs=10)

    # TC-001 has pass/fail/pass (flaky), TC-002 has pass/pass/pass (not flaky)
    assert len(report) == 1
    flaky = report[0]
    assert flaky["test_case_id"] == "TC-001"
    assert flaky["title"] == "Test 1"
    assert flaky["runs"] == 3
    assert flaky["pass_count"] == 2
    assert flaky["fail_count"] == 1
    assert flaky["flip_count"] == 2  # Pass -> Fail -> Pass
    assert flaky["flaky_ratio"] == 0.33
    assert flaky["avg_duration_ms"] == 120.0
    assert flaky["last_status"] == "Pass"


def test_get_flaky_test_report_handles_legacy_records_gracefully(tmp_path):
    db_file = tmp_path / "metrics_db.json"

    # Write synthetic legacy database with missing per_test
    legacy_data = {
        "generations": [],
        "executions": [
            {
                "issue_key": "ZT-LEGACY",
                "timestamp": "2026-09-01T00:00:00",
                "total_tests": 5,
                "passed": 5,
                "failed": 0,
            }
        ],
    }
    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    tracker = MetricsTracker(metrics_db_path=str(db_file))

    # Add new execution with per_test
    tracker.record_execution_metrics("ZT-NEW", {
        "per_test": [
            {"test_case_id": "TC-100", "title": "Flaky test", "status": "Pass", "duration_ms": 50},
        ]
    })
    tracker.record_execution_metrics("ZT-NEW", {
        "per_test": [
            {"test_case_id": "TC-100", "title": "Flaky test", "status": "Fail", "duration_ms": 60},
        ]
    })

    # Should not crash on legacy record
    report = tracker.get_flaky_test_report(n_runs=10)
    assert len(report) == 1
    assert report[0]["test_case_id"] == "TC-100"
    assert report[0]["pass_count"] == 1
    assert report[0]["fail_count"] == 1
