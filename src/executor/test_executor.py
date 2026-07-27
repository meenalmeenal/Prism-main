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

def _parse_nightwatch_summary(combined_output: str) -> Optional[Tuple[int, int, int]]:
    """Parse Nightwatch CLI summary."""
    text = _strip_ansi(combined_output)
    passed = failed = skipped = 0
    saw_any = False
    for line in text.splitlines():
        m = re.search(r"(\d+) passed", line)
        if m:
            passed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) failed", line)
        if m:
            failed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) skipped", line)
        if m:
            skipped = int(m.group(1)); saw_any = True
    return (passed, failed, skipped) if saw_any else None


def _parse_cypress_summary(combined_output: str) -> Optional[Tuple[int, int, int]]:
    """Parse Cypress CLI summary."""
    text = _strip_ansi(combined_output)
    passed = failed = skipped = 0
    saw_any = False
    for line in text.splitlines():
        m = re.search(r"(\d+) passing", line)
        if m:
            passed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) failing", line)
        if m:
            failed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) pending", line)
        if m:
            skipped = int(m.group(1)); saw_any = True
    return (passed, failed, skipped) if saw_any else None


def _parse_cucumber_summary(combined_output: str) -> Optional[Tuple[int, int, int]]:
    """Parse Cucumber.js CLI summary."""
    text = _strip_ansi(combined_output)
    passed = failed = skipped = 0
    saw_any = False
    for line in text.splitlines():
        m = re.search(r"(\d+) passed", line)
        if m:
            passed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) failed", line)
        if m:
            failed = int(m.group(1)); saw_any = True
        m = re.search(r"(\d+) skipped", line)
        if m:
            skipped = int(m.group(1)); saw_any = True
    return (passed, failed, skipped) if saw_any else None


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
        if self.framework == "nightwatch":
            return await self._execute_nightwatch(test_files, issue_key)
        elif self.framework == "cypress":
            return await self._execute_cypress(test_files, issue_key)
        elif self.framework == "gherkin":
            return await self._execute_cucumber(test_files, issue_key)
        else:
            return await self._execute_playwright(test_files, issue_key, headed)
    
    async def _execute_playwright(
        self,
        test_files: List[str],
        issue_key: str,
        headed: bool = True,
    ) -> Dict[str, Any]:
        tests_dir = self.project_root / GENERATED_TESTS_DIR
        config_path = self.project_root / PLAYWRIGHT_CONFIG
        use_config = config_path.is_file()

        logger.info(
            "Executing Playwright suite under %s/ for %s (ui_mode=%s, %d spec path(s) from pipeline)",
            GENERATED_TESTS_DIR, issue_key, headed, len(test_files),
        )

        if not tests_dir.is_dir():
            msg = f"Missing tests directory {tests_dir}"
            logger.warning(msg)
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "test_results": [{"test_name": "playwright_suite", "status": "error", "error": msg}],
                    "parsed_from_output": False}

        target = [Path(f).name for f in test_files] if test_files else [GENERATED_TESTS_DIR]
        pw_args = ["npx", "playwright", "test"] + target
        if use_config:
            pw_args.extend(["--config", PLAYWRIGHT_CONFIG])
        import tempfile, os as _os
        json_report = _os.path.join(str(self.project_root), "playwright-results.json")
        pw_args.extend([f"--reporter=json"])
        cmd = ["cmd", "/c", *pw_args] if sys.platform == "win32" else pw_args
        logger.info("Running: %s (cwd=%s)", " ".join(pw_args), self.project_root)
        return self._run_and_parse_with_json(cmd, issue_key, json_report)

    async def _execute_nightwatch(
        self,
        test_files: List[str],
        issue_key: str,
    ) -> Dict[str, Any]:
        target = [str(Path(f)) for f in test_files] if test_files else [GENERATED_TESTS_DIR]
        cmd_args = ["npx", "nightwatch"] + target + ["--env", "default"]
        cmd = ["cmd", "/c", *cmd_args] if sys.platform == "win32" else cmd_args
        logger.info("Running: %s (cwd=%s)", " ".join(cmd_args), self.project_root)
        return self._run_and_parse(cmd, issue_key, _parse_nightwatch_summary, "nightwatch_suite")

    async def _execute_cypress(
        self,
        test_files: List[str],
        issue_key: str,
    ) -> Dict[str, Any]:
        cmd_args = ["npx", "cypress", "run", "--browser", "chrome", "--headed"]
        if test_files:
            cmd_args += ["--spec", ",".join(test_files)]
        cmd = ["cmd", "/c", *cmd_args] if sys.platform == "win32" else cmd_args
        logger.info("Running: %s (cwd=%s)", " ".join(cmd_args), self.project_root)
        return self._run_and_parse(cmd, issue_key, _parse_cypress_summary, "cypress_suite")

    async def _execute_cucumber(
        self,
        test_files: List[str],
        issue_key: str,
    ) -> Dict[str, Any]:
        cmd_args = ["npx", "cucumber-js", "--config", "cucumber.config.js"]
        cmd = ["cmd", "/c", *cmd_args] if sys.platform == "win32" else cmd_args
        logger.info("Running: %s (cwd=%s)", " ".join(cmd_args), self.project_root)
        return self._run_and_parse(cmd, issue_key, _parse_cucumber_summary, "cucumber_suite")

    def _run_and_parse_with_json(
        self,
        cmd: List[str],
        issue_key: str,
        json_report_path: str,
    ) -> Dict[str, Any]:
        """Run Playwright with --ui and parse results from JSON report file."""
        import json as _json, os as _os
        try:
            process = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            logger.exception("Subprocess failed to start")
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "test_results": [{"test_name": "playwright_suite", "status": "error", "error": str(e)}],
                    "parsed_from_output": False}

        # Try to read the JSON report
        passed = failed = skipped = 0
        parsed_from_output = False
        if _os.path.exists(json_report_path):
            try:
                with open(json_report_path, encoding="utf-8") as f:
                    report = _json.load(f)
                stats = report.get("stats", {})
                passed = stats.get("expected", 0)
                failed = stats.get("unexpected", 0)
                skipped = stats.get("skipped", 0)
                parsed_from_output = True
                logger.info("Parsed JSON report: %d passed, %d failed", passed, failed)
            except Exception as e:
                logger.warning("Failed to parse JSON report: %s", e)

        if not parsed_from_output:
            # Fallback: try stdout parsing
            combined = (process.stdout or "") + "\n" + (process.stderr or "")
            parsed = _parse_playwright_summary(combined)
            if parsed:
                passed, failed, skipped = parsed
                parsed_from_output = True
            else:
                passed = 1 if process.returncode == 0 else 0
                failed = 0 if process.returncode == 0 else 1
                skipped = 0

        total = passed + failed + skipped
        suite_status = "passed" if failed == 0 and process.returncode == 0 else "failed"
        logger.info("Execution complete: %d/%d passed (failed=%d)", passed, total, failed)

        return {
            "issue_key": issue_key,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "skipped": skipped,
            "test_results": [{"test_name": "playwright_suite", "status": suite_status,
                              "stdout": process.stdout, "stderr": process.stderr}],
            "parsed_from_output": parsed_from_output,
        }

    def _run_and_parse(
        self,
        cmd: List[str],
        issue_key: str,
        parser,
        suite_name: str,
    ) -> Dict[str, Any]:
        try:
            process = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            logger.exception("Subprocess failed to start")
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "test_results": [{"test_name": suite_name, "status": "error", "error": str(e)}],
                    "parsed_from_output": False}

        combined = (process.stdout or "") + "\n" + (process.stderr or "")
        parsed = parser(combined)

        if parsed:
            passed, failed, skipped = parsed
            total = passed + failed + skipped
            parsed_from_output = True
        else:
            passed = 1 if process.returncode == 0 else 0
            failed = 0 if process.returncode == 0 else 1
            skipped = 0
            total = 1
            parsed_from_output = False

        suite_status = "passed" if failed == 0 and process.returncode == 0 else "failed"
        logger.info("Execution complete: %d/%d passed (failed=%d)", passed, total, failed)

        return {
            "issue_key": issue_key,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "skipped": skipped,
            "test_results": [{"test_name": suite_name, "status": suite_status,
                              "stdout": process.stdout, "stderr": process.stderr}],
            "parsed_from_output": parsed_from_output,
        }