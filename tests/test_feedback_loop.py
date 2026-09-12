import pytest
from unittest.mock import patch, MagicMock
from src.ai_engine.prompt_templates import PromptTemplates
from src.ai_engine.ai_test_generator import AITestGenerator
from src.feedback.feedback_store import TestFeedback
from src.pipeline.pipeline_runner import run_pipeline
from src.pipeline.enhanced_pipeline import _normalize_status


def test_prompt_builder_byte_identical_when_none_or_empty():
    issue_key = "ZT-10"
    summary = "User login flow"
    acs = ["Valid credentials log user in", "Invalid password shows error"]

    original_prompt = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
    )
    prompt_with_none = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
        past_failures=None,
        resolved_failures=None,
    )
    prompt_with_empty = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
        past_failures=[],
        resolved_failures=[],
    )

    assert original_prompt == prompt_with_none
    assert original_prompt == prompt_with_empty


def test_prompt_builder_includes_failures_and_resolved_sections():
    issue_key = "ZT-10"
    summary = "User login flow"
    acs = ["Valid credentials log user in"]
    failures = [
        TestFeedback(
            test_case_id="ZT-10-TC-001",
            issue_key="ZT-10",
            error_message="Selector '#submit-btn' not found",
            test_steps=[],
            timestamp="2026-09-12T10:00:00",
        )
    ]
    resolved = [
        TestFeedback(
            test_case_id="ZT-10-TC-002",
            issue_key="ZT-10",
            error_message="Timeout loading page",
            test_steps=[],
            timestamp="2026-09-12T09:00:00",
            resolved=True,
        )
    ]

    prompt = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
        past_failures=failures,
        resolved_failures=resolved,
    )

    assert "## Known past failures for this issue (learn from these)" in prompt
    assert "- ZT-10-TC-001 — failed because: Selector '#submit-btn' not found" in prompt
    assert "## Previously fixed for this issue — do not reintroduce" in prompt
    assert "- ZT-10-TC-002 — was failing because: Timeout loading page" in prompt


def test_prompt_builder_resolved_caps_at_5():
    issue_key = "ZT-10"
    summary = "User login flow"
    acs = ["Valid credentials log user in"]
    resolved = [
        {"title": f"FIXED-TC-{i}", "error": f"Error {i}"}
        for i in range(10)
    ]

    prompt = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
        resolved_failures=resolved,
    )

    # Should only have 5 items (FIXED-TC-5 to FIXED-TC-9)
    assert "FIXED-TC-0 — was failing" not in prompt
    assert "FIXED-TC-9 — was failing" in prompt


def test_status_normalizer():
    # Playwright statuses
    assert _normalize_status("passed") == "Pass"
    assert _normalize_status("pass") == "Pass"
    assert _normalize_status("ok") == "Pass"
    assert _normalize_status("failed") == "Fail"
    assert _normalize_status("fail") == "Fail"
    assert _normalize_status("timedOut") == "Fail"
    assert _normalize_status("interrupted") == "Fail"
    assert _normalize_status("error") == "Fail"
    assert _normalize_status("skipped") == "Skip"
    assert _normalize_status("skip") == "Skip"
    # None and unknown values
    assert _normalize_status(None) == "Not Executed"
    assert _normalize_status("unknown_state") == "Not Executed"
    assert _normalize_status("") == "Not Executed"


def test_ai_generator_passes_past_failures_and_resolved_to_prompt_template():
    generator = AITestGenerator()
    generator.client = MagicMock()

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='[{"id": "ZT-10-TC-001-POSITIVE", "title": "Valid login test case with sufficient length", "type": "positive", "priority": "P1", "preconditions": ["User exists"], "steps": [{"step_number": 1, "action": "login", "expected_result": "ok"}], "tags": ["login"]}]'
            )
        )
    ]
    generator._chat_completion = MagicMock(return_value=mock_response)

    past_failures = [
        TestFeedback(
            test_case_id="ZT-10-TC-001",
            issue_key="ZT-10",
            error_message="Element not clickable",
            test_steps=[],
            timestamp="2026-09-12T10:00:00",
        )
    ]
    resolved_failures = [
        TestFeedback(
            test_case_id="ZT-10-TC-002",
            issue_key="ZT-10",
            error_message="Network glitch",
            test_steps=[],
            timestamp="2026-09-12T09:00:00",
            resolved=True,
        )
    ]

    with patch.object(
        PromptTemplates, "get_test_generation_prompt", wraps=PromptTemplates.get_test_generation_prompt
    ) as mock_get_prompt:
        generator.generate_test_cases(
            issue_key="ZT-10",
            summary="User login flow",
            acceptance_criteria=["Valid credentials log user in"],
            past_failures=past_failures,
            resolved_failures=resolved_failures,
        )

        mock_get_prompt.assert_called_once_with(
            issue_key="ZT-10",
            summary="User login flow",
            acceptance_criteria=["Valid credentials log user in"],
            past_failures=past_failures,
            resolved_failures=resolved_failures,
        )


def test_pipeline_runner_handles_feedback_store_failure_gracefully():
    with patch("src.feedback.feedback_store.FeedbackStore.get_feedback_for_issue", side_effect=Exception("DB connection error")), \
         patch("src.integrations.jira_client.JiraClient.get_issue") as mock_get_issue, \
         patch("src.integrations.zephyr_client.ZephyrClient.publish_test_cases", return_value=[]), \
         patch("src.validator.test_validator.TestValidator.validate_all", return_value=([], {"total_input": 0, "total_output": 0})), \
         patch("src.ai_engine.ai_test_generator.AITestGenerator.generate_test_cases", return_value=[]) as mock_ai_gen:

        from src.integrations.jira_client import NormalizedIssue
        mock_get_issue.return_value = NormalizedIssue(
            issue_key="ZT-10",
            summary="Login feature",
            description="",
            acceptance_criteria=["Login works"],
        )

        result = run_pipeline("ZT-10", skip_zephyr=True)

        assert result["issue_key"] == "ZT-10"
        assert mock_ai_gen.call_count == 1
        call_kwargs = mock_ai_gen.call_args[1]
        assert call_kwargs.get("past_failures") is None
        assert call_kwargs.get("resolved_failures") is None


def test_pipeline_runner_masks_pii_in_feedback_items():
    raw_card = "4111 1111 1111 1111"
    raw_email = "alice@example.com"
    raw_error = f"Card {raw_card} failed for user {raw_email}"

    stored_fb = TestFeedback(
        test_case_id="ZT-10-TC-001",
        issue_key="ZT-10",
        error_message=raw_error,
        test_steps=[],
        timestamp="2026-09-12T10:00:00",
    )

    with patch("src.feedback.feedback_store.FeedbackStore.get_feedback_for_issue", return_value=[stored_fb]), \
         patch("src.integrations.jira_client.JiraClient.get_issue") as mock_get_issue, \
         patch("src.integrations.zephyr_client.ZephyrClient.publish_test_cases", return_value=[]), \
         patch("src.validator.test_validator.TestValidator.validate_all", return_value=([], {"total_input": 0, "total_output": 0})), \
         patch("src.ai_engine.ai_test_generator.AITestGenerator.generate_test_cases", wraps=AITestGenerator().generate_test_cases) as mock_ai_gen, \
         patch.object(AITestGenerator, "_chat_completion") as mock_chat:

        mock_chat.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='[]'))]
        )

        from src.integrations.jira_client import NormalizedIssue
        mock_get_issue.return_value = NormalizedIssue(
            issue_key="ZT-10",
            summary="Checkout feature",
            description="",
            acceptance_criteria=["Payment processes"],
        )

        run_pipeline("ZT-10", skip_zephyr=True)

        # 1. Stored object was NOT mutated
        assert stored_fb.error_message == raw_error

        # 2. Generator received masked past_failures
        assert mock_ai_gen.call_count == 1
        passed_failures = mock_ai_gen.call_args[1].get("past_failures")
        assert len(passed_failures) == 1
        masked_error = passed_failures[0].error_message
        assert raw_card not in masked_error
        assert raw_email not in masked_error
        assert "**** **** **** 1111" in masked_error
        assert "[EMAIL]" in masked_error

        # 3. Prompt created in _chat_completion contains neither raw card nor raw email
        assert mock_chat.call_count == 1
        prompt_sent = mock_chat.call_args[1]["messages"][0]["content"]
        assert raw_card not in prompt_sent
        assert raw_email not in prompt_sent
        assert "**** **** **** 1111" in prompt_sent
        assert "[EMAIL]" in prompt_sent


def test_pipeline_runner_handles_none_error_and_masks_steps():
    raw_card = "4111 1111 1111 1111"
    raw_email = "bob@example.com"

    stored_fb = TestFeedback(
        test_case_id="ZT-10-TC-002",
        issue_key="ZT-10",
        error_message=None,
        test_steps=[
            {
                "step_number": 1,
                "action": f"Enter card {raw_card}",
                "test_data": raw_email,
                "expected_result": "Success",
            }
        ],
        timestamp="2026-09-12T10:00:00",
    )

    with patch("src.feedback.feedback_store.FeedbackStore.get_feedback_for_issue", return_value=[stored_fb]), \
         patch("src.integrations.jira_client.JiraClient.get_issue") as mock_get_issue, \
         patch("src.integrations.zephyr_client.ZephyrClient.publish_test_cases", return_value=[]), \
         patch("src.validator.test_validator.TestValidator.validate_all", return_value=([], {"total_input": 0, "total_output": 0})), \
         patch("src.ai_engine.ai_test_generator.AITestGenerator.generate_test_cases", wraps=AITestGenerator().generate_test_cases) as mock_ai_gen, \
         patch.object(AITestGenerator, "_chat_completion") as mock_chat:

        mock_chat.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='[]'))]
        )

        from src.integrations.jira_client import NormalizedIssue
        mock_get_issue.return_value = NormalizedIssue(
            issue_key="ZT-10",
            summary="Checkout feature",
            description="",
            acceptance_criteria=["Payment processes"],
        )

        run_pipeline("ZT-10", skip_zephyr=True)

        # 1. Pipeline still injects feedback
        assert mock_ai_gen.call_count == 1
        passed_failures = mock_ai_gen.call_args[1].get("past_failures")
        assert len(passed_failures) == 1
        masked_steps = passed_failures[0].test_steps
        assert raw_card not in str(masked_steps)
        assert raw_email not in str(masked_steps)
        assert "**** **** **** 1111" in str(masked_steps)
        assert "[EMAIL]" in str(masked_steps)

        # 2. Prompt contains neither raw card nor raw email
        assert mock_chat.call_count == 1
        prompt_sent = mock_chat.call_args[1]["messages"][0]["content"]
        assert raw_card not in prompt_sent
        assert raw_email not in prompt_sent


def test_prompt_builder_renders_title_and_falls_back_to_test_case_id():
    issue_key = "ZT-10"
    summary = "User login flow"
    acs = ["Valid credentials log user in"]

    # Older records with no title
    old_feedback = TestFeedback(
        test_case_id="ZT-10-TC-OLD-001",
        issue_key="ZT-10",
        error_message="Old error without title",
        test_steps=[],
        timestamp="2026-09-12T10:00:00",
    )
    # New records with title
    new_feedback = TestFeedback(
        test_case_id="ZT-10-TC-NEW-002",
        issue_key="ZT-10",
        error_message="New error with title",
        test_steps=[],
        timestamp="2026-09-12T10:05:00",
        title="User checkout with coupon",
    )

    prompt = PromptTemplates.get_test_generation_prompt(
        issue_key=issue_key,
        summary=summary,
        acceptance_criteria=acs,
        past_failures=[old_feedback, new_feedback],
    )

    # Assert old record rendered using test_case_id fallback
    assert "- ZT-10-TC-OLD-001 — failed because: Old error without title" in prompt
    # Assert new record rendered using title
    assert "- User checkout with coupon — failed because: New error with title" in prompt
    # Assert test_case_id of new record is not used as title
    assert "- ZT-10-TC-NEW-002 — failed because" not in prompt
