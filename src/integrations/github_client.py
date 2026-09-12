# src/integrations/github_client.py
import base64
import io
import logging
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from github import Github, GithubException, Auth

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token not provided and GITHUB_TOKEN not set")
        self.client = Github(auth=Auth.Token(self.token.strip()))

    def get_pr_details(self, repo_name: str, pr_number: int) -> Dict:
        """Get PR details including title, body, and files changed."""
        try:
            repo = self.client.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            return {
                "title": pr.title,
                "body": pr.body,
                "author": pr.user.login,
                "created_at": pr.created_at.isoformat(),
                "changed_files": [f.filename for f in pr.get_files()],
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref,
                "head_sha": pr.head.sha,
            }
        except GithubException as e:
            raise Exception(f"GitHub API error: {e}")

    @staticmethod
    def extract_issue_key(pr_title: Optional[str], pr_body: Optional[str]) -> Optional[str]:
        """Extract Jira issue key from PR title or body."""
        import re
        for text in [pr_title, pr_body]:
            if not text:
                continue
            match = re.search(r'([A-Z]+-\d+)', text)
            if match:
                return match.group(1)
        return None

    def set_commit_status(
        self,
        repo_name: str,
        sha: str,
        state: str,  # "pending", "success", "failure", or "error"
        description: str,
        context: str = "prism/zephyr-tests",
        target_url: Optional[str] = None,
    ) -> None:
        """Post a commit status to the PR's head SHA — shows up as a CI
        check (green check / red X) directly on the PR, next to any
        other CI jobs. `target_url` (e.g. a Zephyr cycle link) is
        clickable from the check on GitHub's PR page.
        """
        repo = self.client.get_repo(repo_name)
        commit = repo.get_commit(sha)
        commit.create_status(
            state=state,
            target_url=target_url,
            description=description[:140],  # GitHub truncates past 140 chars
            context=context,
        )

    def push_file(
        self,
        repo_name: str,
        branch: str,
        file_path: str,
        content: str,
        commit_message: str = "chore: add AI-generated tests",
    ) -> None:
        """Create or update a file in the repo on the given branch."""
        try:
            repo = self.client.get_repo(repo_name)
            try:
                existing = repo.get_contents(file_path, ref=branch)
                repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=existing.sha,
                    branch=branch,
                )
            except GithubException:
                repo.create_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    branch=branch,
                )
        except GithubException as e:
            raise Exception(f"Failed to push file {file_path}: {e}")

    # ------------------------------------------------------------------
    # Remote execution via GitHub Actions (EXECUTE_VIA=github_actions)
    #
    # test_executor.py's _execute_via_github_actions() is written against
    # this exact contract:
    #   trigger_workflow(repo_name, workflow_file, ref=..., inputs=...) -> Optional[int]  (a run id)
    #   poll_workflow_run(repo_name, run_id, timeout=..., poll_interval=...) -> Dict
    # A version of this file that returns a bool from trigger_workflow, or
    # that requires poll_workflow_run(branch, trigger_time, timeout_seconds=...)
    # instead, breaks that caller with a TypeError or a silently-wrong run_id.
    # ------------------------------------------------------------------

    def trigger_workflow(
        self,
        repo_name: str,
        workflow_file: str,
        ref: str = "main",
        inputs: Optional[Dict[str, str]] = None,
    ) -> Optional[int]:
        """Dispatch a workflow_dispatch run and return its run id.

        GitHub's dispatch API doesn't hand back a run id synchronously, so we
        record the time just before dispatching, then poll the workflow's
        recent runs for the first one created after that timestamp on the
        same ref. Returns None if dispatch failed or no matching run showed
        up within a few seconds (the API can lag slightly after dispatch).
        """
        repo = self.client.get_repo(repo_name)
        try:
            workflow = repo.get_workflow(workflow_file)
        except GithubException as e:
            raise Exception(f"Workflow '{workflow_file}' not found in {repo_name}: {e}")

        dispatched_at = datetime.now(timezone.utc)
        try:
            ok = workflow.create_dispatch(ref=ref, inputs=inputs or {})
        except GithubException as e:
            raise Exception(f"Failed to trigger workflow: {e}")
        if not ok:
            logger.error("workflow_dispatch call to %s (%s) returned False", workflow_file, repo_name)
            return None

        # Poll briefly for the new run to appear — dispatch is fire-and-forget,
        # the run usually shows up within a couple of seconds.
        for attempt in range(10):
            time.sleep(2)
            runs = workflow.get_runs(branch=ref, event="workflow_dispatch")
            for run in runs:
                if run.created_at.replace(tzinfo=timezone.utc) >= dispatched_at:
                    logger.info("Workflow run %s started for %s", run.id, workflow_file)
                    return run.id
            logger.debug("Run not visible yet (attempt %d/10)", attempt + 1)

        logger.warning(
            "Dispatched %s on %s but couldn't locate the resulting run id after polling",
            workflow_file, ref,
        )
        return None

    def poll_workflow_run(
        self,
        repo_name: str,
        run_id: int,
        timeout: int = 600,
        poll_interval: int = 10,
    ) -> Dict[str, Any]:
        """Block until a workflow run finishes (or timeout), then return its
        status/conclusion plus the list of artifacts it produced."""
        repo = self.client.get_repo(repo_name)
        deadline = time.monotonic() + timeout

        try:
            run = repo.get_workflow_run(run_id)
            while run.status != "completed":
                if time.monotonic() >= deadline:
                    logger.warning("Timed out waiting for workflow run %s to complete", run_id)
                    return {
                        "run_id": run_id,
                        "status": run.status,
                        "conclusion": None,
                        "timed_out": True,
                        "html_url": run.html_url,
                        "artifacts": [],
                    }
                time.sleep(poll_interval)
                run = repo.get_workflow_run(run_id)  # re-fetch; PyGithub objects don't auto-refresh
        except GithubException as e:
            raise Exception(f"Failed to poll workflow run: {e}")

        artifacts = [
            {"id": a.id, "name": a.name, "size_in_bytes": a.size_in_bytes}
            for a in run.get_artifacts()
        ]

        logger.info(
            "Workflow run %s completed: %s (%s)", run_id, run.conclusion, run.status,
        )
        return {
            "run_id": run_id,
            "status": run.status,
            "conclusion": run.conclusion,
            "timed_out": False,
            "html_url": run.html_url,
            "artifacts": artifacts,
        }

    def download_artifact_json(
        self,
        repo_name: str,
        artifact_id: int,
        json_filename: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Download an artifact zip and parse a JSON file out of it.

        If json_filename is omitted, the first *.json entry found is used.
        Artifact downloads require the bearer token directly (PyGithub has no
        high-level helper for this), since the API responds with a redirect
        to a short-lived, pre-signed archive URL.
        """
        import json as _json

        url = f"https://api.github.com/repos/{repo_name}/actions/artifacts/{artifact_id}/zip"
        headers = {
            "Authorization": f"Bearer {self.token.strip()}",
            "Accept": "application/vnd.github+json",
        }
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        if resp.status_code != 200:
            logger.error("Failed to download artifact %s: HTTP %s", artifact_id, resp.status_code)
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                names = zf.namelist()
                target = json_filename if json_filename in names else next(
                    (n for n in names if n.endswith(".json")), None
                )
                if not target:
                    logger.warning("No JSON file found in artifact %s (files: %s)", artifact_id, names)
                    return None
                with zf.open(target) as f:
                    return _json.load(f)
        except zipfile.BadZipFile:
            logger.exception("Artifact %s did not contain a valid zip", artifact_id)
            return None