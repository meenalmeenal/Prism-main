
"""High-level pipeline orchestration for AI test generation.

Flow
----
Jira Issue -> AI Test Generator -> Test Validator -> Zephyr Publisher

This module wires together the existing components into a robust,
production-style service layer with:

- Retry logic for AI generation
- Safe handling of JSON/serialization failures
- Configurable Zephyr publishing + dry‑run support
- Defensive error handling so the CLI never crashes on partial failure
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from src.codegen.automation_generator import AutomationGenerator
from src.integrations.jira_client import JiraClient, NormalizedIssue
from src.integrations.zephyr_client import ZephyrClient
from src.ai_engine.ai_test_generator import AITestGenerator, RuleBasedTestGenerator
from src.executor.test_executor import TestExecutor
from src.validator.test_validator import TestValidator

load_dotenv(override=True)

logger = logging.getLogger(__name__)

# Environment-controlled flag so the fallback strategy can be turned on/off
# without code changes. Default is enabled, which is safe for demos and
# production as it guarantees that test cases are always produced even when
# Gemini is unavailable.
AI_FALLBACK_ENABLED: bool = os.getenv("AI_FALLBACK_ENABLED", "true").lower() in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """Configure root logging if not already configured.

    Individual modules (validator, generator) already configure logging
    to files, but the pipeline is often the entry point for end‑to‑end
    runs and should ensure a sensible default console configuration.
    """

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )


def _fetch_past_failures(
    issue_key: str,
) -> Tuple[Optional[List[Any]], Optional[List[Any]]]:
    """Fetch unresolved and resolved past failures from FeedbackStore for prompt injection.

    Applies mask_pii() to text fields (error_message, test_steps, title) using dataclasses.replace()
    so that the on-disk store remains unmutated while the prompt receives sanitized feedback.
    """
    try:
        from src.feedback.feedback_store import FeedbackStore
        store = FeedbackStore()
        all_feedback = store.get_feedback_for_issue(issue_key, include_resolved=True)
    except Exception as exc:
        logger.warning("Could not load feedback for %s: %s", issue_key, exc)
        return None, None

    from dataclasses import replace, is_dataclass
    from src.utils.pii_masker import mask_pii

    def _mask_step(step: Any) -> Any:
        if isinstance(step, dict):
            return {
                k: mask_pii(str(v or "")) if isinstance(v, str) else v
                for k, v in step.items()
            }
        elif isinstance(step, str):
            return mask_pii(step or "")
        return step

    masked_feedback = []
    for f in all_feedback:
        try:
            # Mask error_message, title, and test_steps (even if PromptTemplates doesn't currently render
            # test_steps, we mask it here so future template changes cannot silently leak PII).
            if is_dataclass(f):
                raw_err = getattr(f, "error_message", None)
                masked_err = mask_pii(raw_err or "") if raw_err is not None else ""
                raw_steps = getattr(f, "test_steps", None) or []
                masked_steps = [_mask_step(s) for s in raw_steps]
                raw_title = getattr(f, "title", None)
                masked_title = mask_pii(raw_title or "") if raw_title is not None else ""

                kwargs = {"error_message": masked_err, "test_steps": masked_steps}
                if hasattr(f, "title"):
                    kwargs["title"] = masked_title
                masked_item = replace(f, **kwargs)
            elif isinstance(f, dict):
                masked_item = dict(f)
                raw_err = masked_item.get("error_message") or masked_item.get("error") or ""
                masked_err = mask_pii(str(raw_err or ""))
                masked_item["error_message"] = masked_err
                if "error" in masked_item:
                    masked_item["error"] = masked_err
                if "title" in masked_item:
                    masked_item["title"] = mask_pii(str(masked_item["title"] or ""))
                if "test_steps" in masked_item and isinstance(masked_item["test_steps"], list):
                    masked_item["test_steps"] = [_mask_step(s) for s in masked_item["test_steps"]]
            else:
                masked_item = f
            masked_feedback.append(masked_item)
        except Exception as exc:
            logger.warning(
                "Failed to mask feedback item %s for %s, skipping: %s",
                getattr(f, "test_case_id", None) or (f.get("test_case_id") if isinstance(f, dict) else None) or "<unknown>",
                issue_key,
                exc,
            )

    unresolved = [
        f for f in masked_feedback
        if not getattr(f, "resolved", False) and not (isinstance(f, dict) and f.get("resolved", False))
    ]
    resolved = [
        f for f in masked_feedback
        if getattr(f, "resolved", False) or (isinstance(f, dict) and f.get("resolved", False))
    ]
    return (unresolved if unresolved else None, resolved if resolved else None)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


# FIXED signature
def run_pipeline(
    issue_key: str,
    max_ai_retries: int = 3,
    retry_delay_seconds: float = 2.0,
    skip_zephyr: bool = False,
    requirements: Optional[Dict[str, Any]] = None,
    framework: str = "playwright",  # ← add this
) -> Dict[str, Any]:
    """Run the full Jira -> AI -> Validator -> Zephyr pipeline.

    Parameters
    ----------
    issue_key:
        Jira issue key to fetch and process.
    max_ai_retries:
        Maximum number of attempts for AI generation before the pipeline
        gives up and continues with zero test cases.
    retry_delay_seconds:
        Delay between retries when AI generation fails.
    skip_zephyr:
        When True, skip Zephyr publishing entirely (useful when the caller
        is already running inside an asyncio event loop).

    Returns
    -------
    Dict[str, Any]
        Structured result object capturing all relevant information,
        including any errors. The pipeline is designed to *not* raise
        exceptions to the caller; instead, failures are encoded in this
        result.
    """

    _configure_logging()
    logger.info("Starting pipeline for Jira issue %s", issue_key)

    jira_client = JiraClient()
    zephyr_client = ZephyrClient()
    ai_generator = AITestGenerator()
    rule_based_generator = RuleBasedTestGenerator()
    validator = TestValidator()

    result: Dict[str, Any] = {
        "issue_key": issue_key,
        "jira_issue": None,
        "jira_error": None,
        "generated_test_cases": [],
        "generation_error": None,
        "validation_stats": None,
        "validated_test_cases": [],
        "zephyr_publish_results": [],
        "zephyr_error": None,
        "automation_results": [],
        "execution_results": {},
        "execution_error": None,
    }

    # 1. Fetch and normalize Jira issue -------------------------------------------------
    if requirements:
        normalized_issue = NormalizedIssue(
            issue_key=issue_key,
            summary=requirements.get("title", "API Spec"),
            description=requirements.get("description", ""),
            acceptance_criteria=requirements.get("acceptance_criteria", [])
        )
        result["jira_issue"] = asdict(normalized_issue)
        logger.info(
            "Using injected requirements for %s (%d ACs)",
            issue_key,
            len(normalized_issue.acceptance_criteria),
        )
    else:
        try:
            normalized_issue: NormalizedIssue = jira_client.get_issue(issue_key)
            result["jira_issue"] = asdict(normalized_issue)
            logger.info(
                "Fetched Jira issue %s (summary length=%d, %d ACs)",
                normalized_issue.issue_key,
                len(normalized_issue.summary or ""),
                len(normalized_issue.acceptance_criteria),
            )
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Failed to fetch Jira issue {issue_key}: {exc}"
            logger.error(msg)
            result["jira_error"] = msg
            return result

    # 2. Generate test cases ------------------------------------------------------------
    past_failures, resolved_failures = _fetch_past_failures(normalized_issue.issue_key)
    logger.info("Injected %d past failures into prompt for %s", len(past_failures or []), normalized_issue.issue_key)

    try:
        from src.utils.pii_masker import mask_pii

        logger.info("Calling Groq AI for issue %s", issue_key)
        generated_cases = ai_generator.generate_test_cases(
            issue_key=normalized_issue.issue_key,
            summary=mask_pii(normalized_issue.summary),
            acceptance_criteria=[mask_pii(ac) for ac in normalized_issue.acceptance_criteria],
            past_failures=past_failures,
            resolved_failures=resolved_failures,
        )
        if generated_cases:
            used_fallback = False
            logger.info("Groq produced %d test cases for %s", len(generated_cases), issue_key)
        else:
            raise ValueError("Groq returned empty list")
    except Exception as exc:
        logger.warning("Groq failed (%s) — falling back to rule-based for %s", exc, issue_key)
        # RuleBasedTestGenerator is purely local template building (offline, no external network transmission)
        generated_cases = rule_based_generator.generate_test_cases(
            issue_key=normalized_issue.issue_key,
            summary=normalized_issue.summary,
            acceptance_criteria=normalized_issue.acceptance_criteria,
            past_failures=past_failures,
            resolved_failures=resolved_failures,
        )
        used_fallback = True

    result["generated_test_cases"] = generated_cases
    if used_fallback:
        logger.info(
            "Rule-based fallback produced %d test cases for %s",
            len(generated_cases),
            issue_key,
        )
        result["generation_mode"] = "fallback_rule_based"
    else:
        logger.info("AI generator produced %d test cases", len(generated_cases))
        result["generation_mode"] = "ai_gemini"

    # If generation completely failed, we still continue but with empty input

    # 3. Validate test cases safely -----------------------------------------------------
    validated_cases: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "total_input": len(generated_cases),
        "total_output": 0,
    }

    if generated_cases:
        try:
            validated_cases, stats = validator.validate_all(generated_cases)
            logger.info(
                "Validation complete: %d/%d cases passed",
                stats.get("total_output", 0),
                stats.get("total_input", len(generated_cases)),
            )
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Validation failed: {exc}"
            logger.error(msg)
            result["validation_error"] = msg
    else:
        logger.warning("Skipping validation: no generated test cases for issue %s", issue_key)

    result["validated_test_cases"] = validated_cases
    result["validation_stats"] = stats

    # 4. Publish to Zephyr mock ---------------------------------------------------------
    publish_results: List[Dict[str, Any]] = []

    if skip_zephyr:
        logger.info("Skipping Zephyr publishing for %s (skip_zephyr=True)", issue_key)
    else:
        if validated_cases:
            publish_results = zephyr_client.publish_test_cases(
                issue_key, validated_cases, issue_id=normalized_issue.issue_id
            )
        else:
            logger.warning("No validated test cases to publish for issue %s", issue_key)

    result["zephyr_publish_results"] = publish_results

    num_published = sum(
        1
        for r in publish_results
        if r.get("status") in {"live"}
    )

    # 5. Codegen + execution (always after Zephyr; uses validated test cases)
    automation_results: List[Dict[str, Any]] = []
    execution_results: Dict[str, Any] = {}
    test_files: List[str] = []

    _framework = framework if framework in AutomationGenerator.SUPPORTED_FRAMEWORKS else os.getenv("PRISM_AUTOMATION_FRAMEWORK", "playwright").strip().lower()

    if validated_cases:
        try:
            auto_gen = AutomationGenerator(framework=_framework)
            automation_results = auto_gen.generate_from_test_cases(
                test_cases=validated_cases,
                issue_key=issue_key,
            )
            result["automation_results"] = automation_results

            test_files = [
                r["file_path"]
                for r in automation_results
                if r.get("status") == "generated" and r.get("file_path")
            ]
            if test_files:
                logger.info("Triggering %s automation...", _framework)
                executor = TestExecutor(framework=_framework)

                async def _run_tests() -> Dict[str, Any]:
                    return await executor.execute_tests(
                        test_files=test_files,
                        issue_key=issue_key,
                    )

                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    execution_results = asyncio.run(_run_tests())
                except ImportError:
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop and loop.is_running():
                        from concurrent.futures import ThreadPoolExecutor
                        def run_in_new_loop(coro):
                            new_loop = asyncio.new_event_loop()
                            try:
                                return new_loop.run_until_complete(coro)
                            finally:
                                new_loop.close()
                        with ThreadPoolExecutor(max_workers=1) as tp_executor:
                            future = tp_executor.submit(run_in_new_loop, _run_tests())
                            execution_results = future.result()
                    else:
                        execution_results = asyncio.run(_run_tests())
                result["execution_results"] = execution_results
            else:
                logger.warning(
                    "No automation files were generated for %s; skipping execution.",
                    issue_key,
                )
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Automation or execution failed: {exc}"
            logger.exception(msg)
            result["execution_error"] = msg
    else:
        logger.info(
            "Skipping automation execution: no validated test cases for %s",
            issue_key,
        )

    logger.info(
        "Pipeline finished for %s: %d generated -> %d validated -> %d published -> execution %s",
        issue_key,
        len(generated_cases),
        stats.get("total_output", 0),
        num_published,
        (
            f"{execution_results.get('passed', 0)}/{execution_results.get('total_tests', 0)} passed"
            if execution_results.get("total_tests")
            else "skipped"
        ),
    )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> None:
    """Command-line entry point.

    Example
    -------
    ::

        python -m src.pipeline.pipeline_runner ZT-3
    """

    import argparse

    _configure_logging()

    parser = argparse.ArgumentParser(description="Run AI test generation pipeline")
    parser.add_argument("issue_key", help="Jira issue key to process, e.g. ZT-3")
    parser.add_argument(
        "--max-ai-retries",
        type=int,
        default=int(os.getenv("MAX_AI_RETRIES", "3")),
        help="Maximum AI generation retry attempts (default: 3)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("AI_RETRY_DELAY_SECONDS", "2.0")),
        help="Delay in seconds between AI retries (default: 2.0)",
    )

    args = parser.parse_args(argv)

    pipeline_result = run_pipeline(
        issue_key=args.issue_key,
        max_ai_retries=args.max_ai_retries,
        retry_delay_seconds=args.retry_delay,
    )

    # Basic human-readable summary on stdout
    jira_error = pipeline_result.get("jira_error")
    generation_error = pipeline_result.get("generation_error")
    zephyr_error = pipeline_result.get("zephyr_error")

    print("\n=== PIPELINE SUMMARY ===")
    print(f"Issue: {pipeline_result['issue_key']}")
    print(f"Generated: {len(pipeline_result['generated_test_cases'])}")
    stats = pipeline_result.get("validation_stats") or {}
    print(f"Validated: {stats.get('total_output', 0)} / {stats.get('total_input', 0)}")
    zephyr_rows = pipeline_result.get("zephyr_publish_results") or []
    zephyr_ok = sum(
        1
        for r in zephyr_rows
        if r.get("status") in {"live"}
    )
    print(f"Zephyr published: {zephyr_ok}")

    exec_res = pipeline_result.get("execution_results") or {}
    total_ex = int(exec_res.get("total_tests") or 0)
    passed_ex = int(exec_res.get("passed") or 0)
    failed_ex = int(exec_res.get("failed") or 0)
    err_ex = int(exec_res.get("errors") or 0)
    if total_ex > 0:
        print(
            f"Execution complete: {passed_ex}/{total_ex} passed "
            f"(failed={failed_ex}, errors={err_ex})"
        )
    else:
        print("Execution: skipped (no specs executed)")

    if jira_error:
        print(f"Jira error: {jira_error}")
    if generation_error:
        print(f"Generation error: {generation_error}")
    if zephyr_error:
        print(f"Zephyr error: {zephyr_error}")
    exec_err = pipeline_result.get("execution_error")
    if exec_err:
        print(f"Execution error: {exec_err}")


if __name__ == "__main__":  # pragma: no cover
    main()
