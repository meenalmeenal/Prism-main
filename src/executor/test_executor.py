import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default output dir for AutomationGenerator; must match playwright.config.js testDir
GENERATED_TESTS_DIR = "generated_tests"
PLAYWRIGHT_CONFIG = "playwright.config.js"


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (Playwright colors output)."""
    if not text:
        return ""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _parse_playwright_summary(combined_output: str) -> Optional[Tuple[int, int, int]]:
    """Parse Playwright CLI summary for passed / failed / skipped counts.

    Typical list-reporter lines (after stripping ANSI)::
        Running 6 tests using 1 worker
        ...
          4 passed (1.2m)
          2 failed

    Returns (passed, failed, skipped) if any summary line matched, else None.
    """
    text = _strip_ansi(combined_output)
    passed = failed = skipped = 0
    saw_passed = saw_failed = saw_skipped = False

    # Match lines like "  4 passed (30.0s)" or "  0 passed" (list reporter)
    passed_re = re.compile(r"^\s*(\d+)\s+passed\b")
    failed_re = re.compile(r"^\s*(\d+)\s+failed\b")
    skipped_re = re.compile(r"^\s*(\d+)\s+skipped\b")

    for line in text.splitlines():
        mp = passed_re.match(line)
        if mp:
            passed = int(mp.group(1))
            saw_passed = True
            continue
        mf = failed_re.match(line)
        if mf:
            failed = int(mf.group(1))
            saw_failed = True
            continue
        ms = skipped_re.match(line)
        if ms:
            skipped = int(ms.group(1))
            saw_skipped = True
            continue

    if saw_passed or saw_failed or saw_skipped:
        return passed, failed, skipped
    return None


class TestExecutor:
    """
    Executes generated Playwright tests.
    Designed to match enhanced_pipeline expectations.
    """

    def __init__(self, framework: str = "playwright"):
        self.framework = framework
        self.project_root = Path.cwd()

        logger.info(f"TestExecutor initialized | framework: {self.framework}")

    async def execute_tests(
        self,
        test_files: List[str],
        issue_key: str,
        headed: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute generated automation tests.

        Runs the full ``generated_tests/`` suite once (same as ``npm test`` /
        ``playwright test`` with root ``playwright.config.js``), not per-file.

        Args:
            test_files: list of generated spec paths (used for logging / sanity;
                execution always targets the whole ``generated_tests`` folder).
            issue_key: jira issue key
            headed: When True (default), run Playwright interactive UI via ``--ui``
                (never ``--headed``; they must not be combined). Set False for default
                CLI run (e.g. headless CI).

        Returns:
            dict containing test_results and aggregate passed/failed from CLI output
        """
        tests_dir = self.project_root / GENERATED_TESTS_DIR
        config_path = self.project_root / PLAYWRIGHT_CONFIG
        use_config = config_path.is_file()

        logger.info(
            "Executing Playwright suite under %s/ for %s (ui_mode=%s, %d spec path(s) from pipeline)",
            GENERATED_TESTS_DIR,
            issue_key,
            headed,
            len(test_files),
        )

        if not use_config:
            logger.warning(
                "%s not found in %s — running without --config (e.g. npx playwright test %s --ui).",
                PLAYWRIGHT_CONFIG,
                self.project_root,
                GENERATED_TESTS_DIR,
            )

        if not tests_dir.is_dir():
            msg = f"Missing tests directory {tests_dir}"
            logger.warning(msg)
            return {
                "issue_key": issue_key,
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "test_results": [
                    {
                        "test_file": f"{GENERATED_TESTS_DIR}/",
                        "test_name": "playwright_suite",
                        "status": "error",
                        "error": msg,
                    }
                ],
                "parsed_from_output": False,
            }

        # Strict shape: npx playwright test [test_files...] [--config playwright.config.js] [--ui]
        # --ui and --headed conflict; demo mode uses --ui only.
        target = [Path(f).name for f in test_files] if test_files else [GENERATED_TESTS_DIR]
        pw_args = ["npx", "playwright", "test"] + target
        if use_config:
            pw_args.extend(["--config", PLAYWRIGHT_CONFIG])
        if headed:
            pw_args.append("--ui")

        if sys.platform == "win32":
            cmd = ["cmd", "/c", *pw_args]
        else:
            cmd = pw_args

        logger.info("Running: %s (cwd=%s)", " ".join(pw_args), self.project_root)

        try:
            process = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
            )
        except Exception as e:
            logger.exception("Playwright subprocess failed to start")
            return {
                "issue_key": issue_key,
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "errors": 1,
                "test_results": [
                    {
                        "test_file": f"{GENERATED_TESTS_DIR}/",
                        "test_name": "playwright_suite",
                        "status": "error",
                        "error": str(e),
                    }
                ],
                "parsed_from_output": False,
            }

        out = process.stdout or ""
        err = process.stderr or ""
        logger.info("Playwright stdout (raw):\n%s", out if out.strip() else "(empty)")
        logger.info("Playwright stderr (raw):\n%s", err if err.strip() else "(empty)")

        combined = out + "\n" + err
        parsed = _parse_playwright_summary(combined)

        if parsed is not None:
            passed, failed, skipped = parsed
            total = passed + failed + skipped
            parsed_from_output = True
            logger.info(
                "Parsed Playwright summary: %d passed, %d failed, %d skipped (total=%d)",
                passed,
                failed,
                skipped,
                total,
            )
        else:
            parsed_from_output = False
            # Fallback: treat whole run as one logical test (legacy behavior)
            passed = 1 if process.returncode == 0 else 0
            failed = 0 if process.returncode == 0 else 1
            skipped = 0
            total = 1
            logger.warning(
                "Could not parse Playwright pass/fail counts from CLI output; "
                "using return code fallback (passed=%d, failed=%d).",
                passed,
                failed,
            )

        if parsed_from_output:
            suite_status = (
                "passed" if failed == 0 and process.returncode == 0 else "failed"
            )
        else:
            suite_status = "passed" if process.returncode == 0 else "failed"

        results = [
            {
                "test_file": f"{GENERATED_TESTS_DIR}/",
                "test_name": "playwright_suite",
                "status": suite_status,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "returncode": process.returncode,
                "parsed_passed": passed if parsed_from_output else None,
                "parsed_failed": failed if parsed_from_output else None,
                "parsed_skipped": skipped if parsed_from_output else None,
            }
        ]

        summary: Dict[str, Any] = {
            "issue_key": issue_key,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "skipped": skipped if parsed_from_output else 0,
            "test_results": results,
            "parsed_from_output": parsed_from_output,
        }

        total = summary["total_tests"]
        ok = summary["passed"]
        logger.info(
            "Execution complete: %d/%d passed (failed=%d, errors=%d, skipped=%s)",
            ok,
            total,
            summary["failed"],
            summary["errors"],
            summary.get("skipped", 0),
        )

        return summary
