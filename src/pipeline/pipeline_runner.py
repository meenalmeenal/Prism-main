"""High-level pipeline orchestration for AI test generation.

Flow
----
Jira Issue -> AI Test Generator -> Test Validator -> Zephyr Publisher (mock)

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

load_dotenv()

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


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    issue_key: str,
    max_ai_retries: int = 3,
    retry_delay_seconds: float = 2.0,
    skip_zephyr: bool = False,
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
        # We can still attempt to proceed with a mocked issue from JiraClient,
        # but if even that failed there's nothing meaningful to do.
        return result

    # 2. Generate test cases (rule-based only in this phase) ---------------------------
    try:
        logger.info("Calling Groq AI for issue %s", issue_key)
        generated_cases = ai_generator.generate_test_cases(
            issue_key=normalized_issue.issue_key,
            summary=normalized_issue.summary,
            acceptance_criteria=normalized_issue.acceptance_criteria,
        )
        if generated_cases:
            used_fallback = False
            logger.info("Groq produced %d test cases for %s", len(generated_cases), issue_key)
        else:
            raise ValueError("Groq returned empty list")
    except Exception as exc:
        logger.warning("Groq failed (%s) — falling back to rule-based for %s", exc, issue_key)
        generated_cases = rule_based_generator.generate_test_cases(
            issue_key=normalized_issue.issue_key,
            summary=normalized_issue.summary,
            acceptance_criteria=normalized_issue.acceptance_criteria,
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
            # Sync API: tries Zephyr Scale REST when token present; else Zephyr Demo Mode (never raises)
            publish_results = zephyr_client.publish_test_cases(issue_key, validated_cases)
        else:
            logger.warning("No validated test cases to publish for issue %s", issue_key)

    result["zephyr_publish_results"] = publish_results

    num_published = sum(
        1
        for r in publish_results
        if r.get("status") in {"mock_published", "dry_run", "demo_mode", "live"}
    )

    # 5. Playwright codegen + execution (always after Zephyr; uses validated test cases)
    automation_results: List[Dict[str, Any]] = []
    execution_results: Dict[str, Any] = {}
    test_files: List[str] = []

    if validated_cases:
        try:
            framework = os.getenv("PRISM_AUTOMATION_FRAMEWORK", "playwright").strip().lower()
            if framework not in AutomationGenerator.SUPPORTED_FRAMEWORKS:
                framework = "playwright"
            auto_gen = AutomationGenerator(framework=framework)
            automation_results = auto_gen.generate_from_test_cases(
                test_cases=validated_cases,
                issue_key=issue_key,
            )
            test_files = [
                r["file_path"]
                for r in automation_results
                if r.get("status") == "generated" and r.get("file_path")
            ]
            result["automation_results"] = automation_results

            if test_files:
                logger.info("Triggering Playwright automation...")
                executor = TestExecutor(framework=framework)

                async def _run_playwright() -> Dict[str, Any]:
                    return await executor.execute_tests(
                        test_files=test_files,
                        issue_key=issue_key,
                    )

                """execution_results = asyncio.run(_run_playwright())"""
                import nest_asyncio
                nest_asyncio.apply()
                execution_results = asyncio.run(_run_playwright())
                result["execution_results"] = execution_results
            else:
                logger.warning(
                    "No automation files were generated for %s; skipping Playwright execution.",
                    issue_key,
                )
        except Exception as exc:  # pragma: no cover - defensive
            msg = f"Automation or Playwright execution failed: {exc}"
            logger.exception(msg)
            result["execution_error"] = msg
    else:
        logger.info(
            "Skipping automation and Playwright: no validated test cases for %s",
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
        if r.get("status") in {"mock_published", "dry_run", "demo_mode", "live"}
    )
    print(f"Zephyr published (demo/live): {zephyr_ok}")

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
        print("Execution: skipped (no Playwright specs executed)")

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
