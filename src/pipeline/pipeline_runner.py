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

# Zephyr publish result statuses that carry a real (usable) execution_id and
# are therefore eligible for post-run sync. "live" = real API publish,
# "demo" = ZEPHYR_DRY_RUN mock publish (also carries a synthetic but usable
# execution_id, and zephyr_client's sync path has an explicit dry_run branch
# built specifically to handle these).
SYNCABLE_ZEPHYR_STATUSES = {"live", "demo"}


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


# FIXED signature
def run_pipeline(
    issue_key: str,
    max_ai_retries: int = 3,
    retry_delay_seconds: float = 2.0,
    skip_zephyr: bool = False,
    requirements: Optional[Dict[str, Any]] = None,
    framework: str = "playwright",  # ← add this
    team: Optional[str] = None,
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
    framework:
        Automation framework to generate/execute scripts with
        (playwright, cypress, nightwatch, or gherkin).
    team:
        Optional team name tag attached to this pipeline run for reporting
        purposes.

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
        "team": team,
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
        "zephyr_sync_results": [],
        "zephyr_sync_error": None,
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

    # 2. Generate test cases, retrying Groq up to max_ai_retries times before
    #    falling back to rule-based generation ----------------------------------------
    from src.utils.pii_masker import mask_pii

    generated_cases: List[Dict[str, Any]] = []
    used_fallback = False
    last_ai_error: Optional[Exception] = None

    for attempt in range(1, max(1, max_ai_retries) + 1):
        try:
            logger.info(
                "Calling Groq AI for issue %s (attempt %d/%d)",
                issue_key, attempt, max_ai_retries,
            )
            generated_cases = ai_generator.generate_test_cases(
                issue_key=normalized_issue.issue_key,
                summary=mask_pii(normalized_issue.summary),
                acceptance_criteria=[mask_pii(ac) for ac in normalized_issue.acceptance_criteria],
            )
            if generated_cases:
                logger.info(
                    "Groq produced %d test cases for %s on attempt %d",
                    len(generated_cases), issue_key, attempt,
                )
                break
            raise ValueError("Groq returned empty list")
        except Exception as exc:
            last_ai_error = exc
            logger.warning(
                "Groq attempt %d/%d failed for %s: %s",
                attempt, max_ai_retries, issue_key, exc,
            )
            if attempt < max_ai_retries:
                time.sleep(retry_delay_seconds)

    if not generated_cases:
        logger.warning(
            "Groq failed after %d attempt(s) (%s) — falling back to rule-based for %s",
            max_ai_retries, last_ai_error, issue_key,
        )
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

    # 4. Publish to Zephyr ---------------------------------------------------------------
    publish_results: List[Dict[str, Any]] = []

    if skip_zephyr:
        logger.info("Skipping Zephyr publishing for %s (skip_zephyr=True)", issue_key)
    else:
        if validated_cases:
            try:
                publish_results = zephyr_client.publish_test_cases(
                    issue_key, validated_cases, issue_id=normalized_issue.issue_id
                )
            except Exception as exc:  # pragma: no cover - defensive
                msg = f"Zephyr publishing failed: {exc}"
                logger.error(msg)
                result["zephyr_error"] = msg
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
                    # pyrefly: ignore [missing-import]
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

                # 6. Sync real per-test pass/fail back to Zephyr -----------------------
                # Only meaningful if we actually published (have execution_ids to
                # target) and the executor produced a per-test breakdown to sync.
                # NOTE: includes both "live" (real API publish) and "demo"
                # (ZEPHYR_DRY_RUN mock publish) statuses — both carry a usable
                # execution_id, and zephyr_client.sync_execution_results() has
                # a dedicated dry_run branch specifically for the latter. An
                # earlier version of this filter only matched "live", which
                # silently disabled sync entirely whenever ZEPHYR_DRY_RUN=true.
                per_test_results = execution_results.get("per_test") or []
                if not skip_zephyr and publish_results and per_test_results:
                    try:
                        test_case_id_to_execution_id = {
                            r["test_case_id"]: r["execution_id"]
                            for r in publish_results
                            if r.get("test_case_id")
                            and r.get("execution_id")
                            and r.get("status") in SYNCABLE_ZEPHYR_STATUSES
                        }
                        if test_case_id_to_execution_id:
                            sync_results = zephyr_client.sync_execution_results(
                                test_case_id_to_execution_id, per_test_results
                            )
                            result["zephyr_sync_results"] = sync_results
                            synced_ok = sum(1 for s in sync_results if s.get("synced"))
                            logger.info(
                                "Synced %d/%d real execution result(s) back to Zephyr for %s",
                                synced_ok, len(sync_results), issue_key,
                            )
                        else:
                            logger.info(
                                "No syncable Zephyr executions with matching test_case_id for %s",
                                issue_key,
                            )
                    except Exception as exc:  # pragma: no cover - defensive
                        msg = f"Failed to sync execution results to Zephyr: {exc}"
                        logger.error(msg)
                        result["zephyr_sync_error"] = msg
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
    parser.add_argument(
        "--framework",
        type=str,
        default=os.getenv("PRISM_AUTOMATION_FRAMEWORK", "playwright"),
        help="Automation framework to use: playwright, nightwatch, cypress, or gherkin (default: playwright)",
    )
    parser.add_argument(
        "--team",
        type=str,
        default=None,
        help="Optional team name tag for this pipeline run",
    )

    args = parser.parse_args(argv)

    pipeline_result = run_pipeline(
        issue_key=args.issue_key,
        max_ai_retries=args.max_ai_retries,
        retry_delay_seconds=args.retry_delay,
        framework=args.framework,
        team=args.team,
    )

    # Basic human-readable summary on stdout
    jira_error = pipeline_result.get("jira_error")
    generation_error = pipeline_result.get("generation_error")
    zephyr_error = pipeline_result.get("zephyr_error")

    print("\n=== PIPELINE SUMMARY ===")
    print(f"Issue: {pipeline_result['issue_key']}")
    if pipeline_result.get("team"):
        print(f"Team: {pipeline_result['team']}")
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

    sync_rows = pipeline_result.get("zephyr_sync_results") or []
    if sync_rows:
        synced_ok = sum(1 for s in sync_rows if s.get("synced"))
        print(f"Zephyr execution sync: {synced_ok}/{len(sync_rows)} results synced")

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