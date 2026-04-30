"""Enhanced end‑to‑end test generation pipeline.

This module provides a higher‑level orchestration entry point that:

- Accepts either a Jira issue key or a GitHub PR URL
- Runs the core Jira → AI → Validator → Zephyr pipeline
- Generates automation code (Playwright/Nightwatch/Cypress)
- Optionally executes the generated tests
- Records metrics for dashboards
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()


from src.collector.pr_collector import PRCollector
from src.dashboard.metrics_tracker import MetricsTracker
from src.executor.test_executor import TestExecutor
from src.pipeline.pipeline_runner import run_pipeline
from src.codegen.automation_generator import AutomationGenerator
from src.feedback.feedback_store import FeedbackStore, TestFeedback
from datetime import datetime
import json


logger = logging.getLogger(__name__)


async def run_enhanced_pipeline_async(
    source: str,  # 'jira' or 'github_pr'
    identifier: str,  # Jira issue key or GitHub PR URL
    framework: str = "playwright",
    team: Optional[str] = None,
    max_ai_retries: int = 3,
    retry_delay_seconds: float = 2.0,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run the enhanced test generation pipeline asynchronously.

    Parameters
    ----------
    source:
        'jira' or 'github_pr'
    identifier:
        Jira issue key (e.g. ZT-123) or GitHub PR URL
    framework:
        Target automation framework: playwright, nightwatch, or cypress
    max_ai_retries:
        Maximum AI generation retries (passed through to core pipeline)
    retry_delay_seconds:
        Delay between AI retries
    dry_run:
        When True, Zephyr operations run in mock mode via ZEPHYR_DRY_RUN.
    """

    logger.info("=== Starting Enhanced Prism Pipeline ===")
    if team:
        logger.info("Team context: %s", team)

    # Honour dry‑run flag for Zephyr integration
    if dry_run:
        os.environ["ZEPHYR_DRY_RUN"] = "true"

    def _resolve_issue_key(single_identifier: str) -> str:
        if source == "jira":
            return single_identifier
        elif source == "github_pr":
            pr_collector = PRCollector()
            pr_data = pr_collector.process_pr_url(single_identifier)
            ikey = pr_data.get("issue_key") or f"PR-{abs(hash(single_identifier))}"
            logger.info("Resolved PR %s to issue key %s", single_identifier, ikey)
            return ikey
        else:
            raise ValueError(f"Unsupported source: {source}")

    # Support batch processing of multiple Jira IDs in a simple way:
    identifiers: List[str]
    if source == "jira" and "," in identifier:
        identifiers = [part.strip() for part in identifier.split(",") if part.strip()]
        logger.info("Batch mode: processing %d Jira issues", len(identifiers))
    else:
        identifiers = [identifier]

    all_results: List[Dict[str, Any]] = []

    for single_identifier in identifiers:
        issue_key = _resolve_issue_key(single_identifier)

        # ------------------------------------------------------------------
        # 1) Core Jira -> AI (disabled) -> Validator -> Zephyr (skipped here)
        # ------------------------------------------------------------------
        core_result = run_pipeline(
            issue_key=issue_key,
            max_ai_retries=max_ai_retries,
            retry_delay_seconds=retry_delay_seconds,
            skip_zephyr=False,
        )

        generated_cases: List[Dict[str, Any]] = core_result.get("generated_test_cases", [])
        validated_cases: List[Dict[str, Any]] = core_result.get("validated_test_cases", []) or generated_cases

        # Steps 2 & 3 already handled by pipeline_runner (codegen + execution)
        automation_results: List[Dict[str, Any]] = core_result.get("automation_results", [])
        execution_results: Dict[str, Any] = core_result.get("execution_results", {})

        # ------------------------------------------------------------------
        # 4) Feedback collection (failed tests)
        # ------------------------------------------------------------------
        feedback_entries: List[Dict[str, Any]] = []
        if execution_results:
            store = FeedbackStore()
            for tr in execution_results.get("test_results", []):
                if tr.get("status") not in {"failed", "error"}:
                    continue
                fb = TestFeedback(
                    test_case_id=tr.get("test_name", tr.get("test_file", "unknown")),
                    issue_key=issue_key,
                    error_message=tr.get("error", tr.get("stderr", "")) or "Unknown error",
                    test_steps=[],
                    timestamp=datetime.now().isoformat(),
                )
                store.add_feedback(fb)
                feedback_entries.append(fb.__dict__)
            if feedback_entries:
                logger.info("Feedback recorded for AI improvement (%d entries)", len(feedback_entries))

        # ------------------------------------------------------------------
        # 5) Metrics for dashboards
        # ------------------------------------------------------------------
        tracker = MetricsTracker()
        tracker.record_test_generation(issue_key, generated_cases, generation_time=0.0)
        if execution_results:
            tracker.record_execution_metrics(issue_key, execution_results)

        enhanced_result: Dict[str, Any] = {
            "issue_key": issue_key,
            "source": source,
            "team": team,
            "core_pipeline": core_result,
            "automation": automation_results,
            "execution": execution_results,
            "feedback": feedback_entries,
        }

        logger.info(
            "Enhanced pipeline finished for %s: %d generated -> %d validated -> %d tests executed",
            issue_key,
            len(generated_cases),
            len(validated_cases),
            len(automation_results),
        )

        all_results.append(enhanced_result)

    # Generate dashboard metrics JSON for all runs
    tracker = MetricsTracker()
    dashboard_data = tracker.generate_dashboard_data()
    os.makedirs("data", exist_ok=True)
    dashboard_path = os.path.join("data", "dashboard_data.json")
    with open(dashboard_path, "w", encoding="utf-8") as f:
        json.dump(dashboard_data, f, indent=2, ensure_ascii=False)
    logger.info("Dashboard data written to %s", dashboard_path)

    # If only one result, return it directly for backward compatibility
    return all_results[0] if len(all_results) == 1 else {"batch_results": all_results}


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point for the enhanced pipeline.

    Examples
    --------
    Jira issue:
        python -m src.pipeline.enhanced_pipeline jira ZT-123 --framework playwright

    GitHub PR:
        python -m src.pipeline.enhanced_pipeline github_pr https://github.com/org/repo/pull/123
    """

    parser = argparse.ArgumentParser(description="Run enhanced AI test generation pipeline")
    parser.add_argument("source", choices=["jira", "github_pr"], help="Input source type")
    parser.add_argument("identifier", help="Jira issue key or GitHub PR URL")
    parser.add_argument(
        "--framework",
        default="playwright",
        choices=["playwright", "nightwatch", "cypress"],
        help="Target automation framework (default: playwright)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.getenv("MAX_AI_RETRIES", "3")),
        help="Maximum AI generation retry attempts (default: 3)",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=float(os.getenv("AI_RETRY_DELAY_SECONDS", "2.0")),
        help="Delay between AI retries in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making real Zephyr API calls (forces ZEPHYR_DRY_RUN=true)",
    )
    parser.add_argument(
        "--team",
        help="Optional team name for tagging runs (also honoured from TEAM_NAME env)",
    )

    args = parser.parse_args(argv)

    # Ensure basic logging if not already configured
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    team = args.team or os.getenv("TEAM_NAME")

    result = asyncio.run(
        run_enhanced_pipeline_async(
            source=args.source,
            identifier=args.identifier,
            framework=args.framework,
            max_ai_retries=args.max_retries,
            retry_delay_seconds=args.retry_delay,
            dry_run=args.dry_run,
            team=team,
        )
    )

    if "batch_results" in result:
        batch = result["batch_results"]
        print("\n=== ENHANCED PIPELINE SUMMARY (BATCH) ===")
        print(f"Issues processed: {len(batch)}")
        total_gen = total_val_out = total_val_in = total_z = total_auto = 0
        total_exec = total_pass = total_fail = 0
        for item in batch:
            c = item.get("core_pipeline") or {}
            total_gen += len(c.get("generated_test_cases", []))
            st = c.get("validation_stats") or {}
            total_val_out += st.get("total_output", 0)
            total_val_in += st.get("total_input", 0)
            total_z += len(c.get("zephyr_publish_results", []))
            total_auto += len(item.get("automation") or [])
            ex = item.get("execution") or {}
            total_exec += ex.get("total_tests", 0)
            total_pass += ex.get("passed", 0)
            total_fail += ex.get("failed", 0)
        print(f"Generated (total): {total_gen}")
        print(f"Validated (total): {total_val_out} / {total_val_in}")
        print(f"Zephyr published (total): {total_z}")
        print(f"Automation files (total): {total_auto}")
        print(f"Executed tests (total): {total_exec} (passed={total_pass}, failed={total_fail})")
    else:
        core = result.get("core_pipeline", {})
        execution = result.get("execution") or {}

        print("\n=== ENHANCED PIPELINE SUMMARY ===")
        print(f"Issue: {result.get('issue_key')}")
        print(f"Source: {result.get('source')}")
        print(f"Generated: {len(core.get('generated_test_cases', []))}")
        stats = core.get("validation_stats") or {}
        print(f"Validated: {stats.get('total_output', 0)} / {stats.get('total_input', 0)}")
        print(f"Zephyr published (demo/live): {len(core.get('zephyr_publish_results', []))}")
        print(f"Automation files: {len(result.get('automation') or [])}")
        if execution:
            print(
                f"Executed tests: {execution.get('total_tests', 0)} "
                f"(passed={execution.get('passed', 0)}, failed={execution.get('failed', 0)})"
            )


if __name__ == "__main__":  # pragma: no cover
    main()