import pytest
from src.feedback.feedback_store import FeedbackStore, TestFeedback


def test_feedback_store_mark_resolved(tmp_path):
    storage_file = tmp_path / "feedback.json"
    store = FeedbackStore(storage_path=str(storage_file))

    fb1 = TestFeedback(
        test_case_id="TC-101",
        issue_key="ZT-1",
        error_message="Button not clickable",
        test_steps=[],
        timestamp="2026-09-12T10:00:00",
    )
    fb2 = TestFeedback(
        test_case_id="TC-102",
        issue_key="ZT-1",
        error_message="Timeout loading page",
        test_steps=[],
        timestamp="2026-09-12T10:05:00",
    )
    store.add_feedback(fb1)
    store.add_feedback(fb2)

    # Initial state: 2 unresolved feedbacks
    unresolved = store.get_feedback_for_issue("ZT-1")
    assert len(unresolved) == 2
    assert {f.test_case_id for f in unresolved} == {"TC-101", "TC-102"}

    # Mark TC-101 as resolved
    result = store.mark_resolved("TC-101", resolved_at="2026-09-12T10:30:00")
    assert result is True

    # Now get_feedback_for_issue default should only return TC-102
    unresolved_after = store.get_feedback_for_issue("ZT-1")
    assert len(unresolved_after) == 1
    assert unresolved_after[0].test_case_id == "TC-102"

    # include_resolved=True should return both TC-101 and TC-102
    all_feedback = store.get_feedback_for_issue("ZT-1", include_resolved=True)
    assert len(all_feedback) == 2
    resolved_item = next(f for f in all_feedback if f.test_case_id == "TC-101")
    assert resolved_item.resolved is True
    assert resolved_item.resolved_at == "2026-09-12T10:30:00"

    # Idempotent call on TC-101 returns True again
    assert store.mark_resolved("TC-101") is True

    # Unknown ID returns False
    assert store.mark_resolved("UNKNOWN-TC-999") is False


def test_feedback_store_persists_across_instances(tmp_path):
    storage_file = tmp_path / "feedback.json"
    store1 = FeedbackStore(storage_path=str(storage_file))
    store1.add_feedback(
        TestFeedback(
            test_case_id="TC-200",
            issue_key="ZT-2",
            error_message="Network error",
            test_steps=[],
            timestamp="2026-09-12T11:00:00",
        )
    )
    store1.mark_resolved("TC-200")

    # Reload from same file
    store2 = FeedbackStore(storage_path=str(storage_file))
    assert len(store2.get_feedback_for_issue("ZT-2")) == 0
    all_fb = store2.get_feedback_for_issue("ZT-2", include_resolved=True)
    assert len(all_fb) == 1
    assert all_fb[0].resolved is True
