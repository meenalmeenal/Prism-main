import logging
import os
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



# AutomationGenerator uses compound extensions ("spec.js"), so a naive single
# rsplit(".", 1) leaves ".spec" stuck on the recovered id. Strip the whole
# known suffix explicitly instead.
_KNOWN_SPEC_SUFFIXES = (".spec.js", ".feature", ".js")


def _extract_test_case_id(file_path: Optional[str], issue_key: str) -> Optional[str]:
    """Recover Prism's internal test_case_id from a generated spec's filename.

    AutomationGenerator names files f"{issue_key}_{test_id}.{ext}" where ext is
    "spec.js" (Playwright/Cypress) or "feature" (Gherkin) — this is the inverse
    of that. Falls back to stripping the last dotted segment, then to the bare
    filename stem, if the issue_key prefix or a known suffix isn't present.
    """
    if not file_path:
        return None
    name = Path(file_path).name
    stem = name
    for suffix in _KNOWN_SPEC_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    else:
        stem = stem.rsplit(".", 1)[0]

    prefix = f"{issue_key}_"
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return stem


def _walk_playwright_suites(suites: List[Dict[str, Any]], file_hint: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recursively walk Playwright's JSON-reporter `suites` tree.

    Playwright nests one suite per file, which may itself contain nested
    suites per describe() block, each eventually holding `specs`. This walks
    all of it and returns a flat list of per-spec results with the owning
    file path, aggregated status, and total duration across retries.
    """
    per_spec: List[Dict[str, Any]] = []
    for suite in suites or []:
        file_path = suite.get("file") or file_hint

        for spec in suite.get("specs", []) or []:
            title = spec.get("title", "")
            total_duration_ms = 0
            final_status = "skipped"
            error_msg: Optional[str] = None

            for test in spec.get("tests", []) or []:
                for res in test.get("results", []) or []:
                    total_duration_ms += res.get("duration", 0) or 0
                    status = res.get("status")
                    if status:
                        final_status = status
                    if status in {"failed", "timedOut"} and res.get("error"):
                        error_msg = (res.get("error") or {}).get("message")

            per_spec.append({
                "file": file_path,
                "title": title,
                "status": final_status,
                "duration_ms": total_duration_ms,
                "error": error_msg,
            })

        # Recurse into nested suites (describe blocks), carrying the file down
        per_spec.extend(_walk_playwright_suites(suite.get("suites"), file_hint=file_path))

    return per_spec


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
        if os.getenv("EXECUTE_VIA", "local").lower() == "github_actions":
            return await self._execute_via_github_actions(issue_key)
        if self.framework == "nightwatch":
            return await self._execute_nightwatch(test_files, issue_key)
        elif self.framework == "cypress":
            return await self._execute_cypress(test_files, issue_key)
        elif self.framework == "gherkin":
            return await self._execute_cucumber(test_files, issue_key)
        else:
            return await self._execute_playwright(test_files, issue_key, headed)
    
    async def _execute_via_github_actions(self, issue_key: str) -> Dict[str, Any]:
        """Remote execution mode (EXECUTE_VIA=github_actions): dispatch the
        existing 'Full Prism Pipeline' workflow for this issue and poll for
        completion, instead of running the automation suite as a local
        subprocess.

        Known limitation: full_pipeline.yml re-runs generation + publish +
        execution together as one remote job — it wasn't built to just
        execute a set of already-generated local spec files — so this mode
        currently surfaces run-level status/artifacts, not a per-test
        breakdown. `per_test` comes back empty here, which means
        sync_execution_results() has nothing to push back to Zephyr for a
        run triggered this way. Splitting the workflow so a per-test JSON
        artifact comes back in the same shape the local JSON-report path
        produces is a follow-up, not something this flag alone solves —
        flagging it rather than quietly returning a shape that looks
        complete but isn't.
        """
        from src.integrations.github_client import GitHubClient

        repo_name = os.environ.get("GITHUB_REPO")
        if not repo_name:
            msg = "EXECUTE_VIA=github_actions requires GITHUB_REPO (e.g. 'org/repo') to be set"
            logger.error(msg)
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "duration_seconds": 0.0, "per_test": [],
                    "test_results": [{"test_name": "github_actions_dispatch", "status": "error", "error": msg}],
                    "parsed_from_output": False}

        workflow_file = os.getenv("EXECUTE_VIA_WORKFLOW_FILE", "full_pipeline.yml")
        ref = os.getenv("EXECUTE_VIA_REF", "main")
        timeout = int(os.getenv("EXECUTE_VIA_TIMEOUT", "900"))

        client = GitHubClient()
        logger.info("Dispatching %s on %s (ref=%s) for %s", workflow_file, repo_name, ref, issue_key)
        run_id = client.trigger_workflow(repo_name, workflow_file, ref=ref, inputs={"issue_key": issue_key})
        if run_id is None:
            msg = "Failed to dispatch workflow or locate the resulting run id"
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "duration_seconds": 0.0, "per_test": [],
                    "test_results": [{"test_name": "github_actions_dispatch", "status": "error", "error": msg}],
                    "parsed_from_output": False}

        run_result = client.poll_workflow_run(repo_name, run_id, timeout=timeout)
        conclusion = run_result.get("conclusion")
        suite_status = "passed" if conclusion == "success" else "failed"

        return {
            "issue_key": issue_key,
            "total_tests": 0,
            "passed": 1 if conclusion == "success" else 0,
            "failed": 0 if conclusion == "success" else 1,
            "errors": 0,
            "duration_seconds": 0.0,
            "per_test": [],  # see docstring — remote mode doesn't produce per-test detail yet
            "test_results": [{
                "test_name": "github_actions_run",
                "status": suite_status,
                "run_id": run_id,
                "html_url": run_result.get("html_url"),
                "artifacts": run_result.get("artifacts"),
                "timed_out": run_result.get("timed_out"),
            }],
            "parsed_from_output": False,
            "remote_run": run_result,
        }

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
                    "errors": 1, "duration_seconds": 0.0, "per_test": [],
                    "test_results": [{"test_name": "playwright_suite", "status": "error", "error": msg}],
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
        """Run Playwright and parse results from the JSON report file."""
        import json as _json, os as _os
        try:
            env = _os.environ.copy()
            env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = json_report_path
            process = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except Exception as e:
            logger.exception("Subprocess failed to start")
            return {"issue_key": issue_key, "total_tests": 0, "passed": 0, "failed": 0,
                    "errors": 1, "duration_seconds": 0.0, "per_test": [],
                    "test_results": [{"test_name": "playwright_suite", "status": "error", "error": str(e)}],
                    "parsed_from_output": False}

        # Try to read the JSON report
        passed = failed = skipped = 0
        parsed_from_output = False
        per_test: List[Dict[str, Any]] = []
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

                raw_specs = _walk_playwright_suites(report.get("suites", []))
                for spec in raw_specs:
                    per_test.append({
                        "test_case_id": _extract_test_case_id(spec["file"], issue_key),
                        "title": spec["title"],
                        "status": spec["status"],
                        "duration_ms": spec["duration_ms"],
                        "error": spec["error"],
                    })
                logger.info("Extracted per-test results for %d spec(s)", len(per_test))
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
        duration_seconds = round(sum(pt["duration_ms"] for pt in per_test) / 1000.0, 3) if per_test else 0.0
        logger.info("Execution complete: %d/%d passed (failed=%d)", passed, total, failed)

        return {
            "issue_key": issue_key,
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": 0,
            "skipped": skipped,
            "duration_seconds": duration_seconds,
            "per_test": per_test,
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
                    "errors": 1, "duration_seconds": 0.0, "per_test": [],
                    "test_results": [{"test_name": suite_name, "status": "error", "error": str(e)}],
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
            "duration_seconds": 0.0,
            "per_test": [],  # Nightwatch/Cypress/Cucumber suites: no per-spec JSON report parsed yet
            "test_results": [{"test_name": suite_name, "status": suite_status,
                              "stdout": process.stdout, "stderr": process.stderr}],
            "parsed_from_output": parsed_from_output,
        }