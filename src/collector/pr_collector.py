from typing import Dict, Optional
from ..integrations.github_client import GitHubClient
from src.utils.pii_masker import mask_pii

class PRCollector:
    def __init__(self, github_client: Optional[GitHubClient] = None):
        self.github = github_client or GitHubClient()

    def process_pr_url(self, pr_url: str) -> Dict:
        try:
            repo_name, pr_number = self._parse_pr_url(pr_url)
            if not repo_name or not pr_number:
                raise ValueError("Invalid GitHub PR URL")
                
            pr_details = self.github.get_pr_details(repo_name, pr_number)
            issue_key = self.github.extract_issue_key(
                pr_details["title"], 
                pr_details["body"]
            )
            
            return {
                "source": "github_pr",
                "issue_key": issue_key,
                "title": mask_pii(pr_details["title"]),
                "description": mask_pii(pr_details["body"]),
                "metadata": {
                    "pr_url": pr_url,
                    "author": pr_details["author"],
                    "changed_files": pr_details["changed_files"],
                    "base_branch": pr_details["base_branch"],
                    "head_branch": pr_details["head_branch"],
                    "head_sha": pr_details["head_sha"],
                }
            }
        except Exception as e:
            raise Exception(f"Failed to process PR: {str(e)}")

    def report_status(
        self,
        pr_url: str,
        state: str,
        description: str,
        target_url: Optional[str] = None,
        context: str = "prism/zephyr-tests",
    ) -> None:
        """Post a CI-style commit status to the PR's head commit.
        Shows up as a check (green/red) directly on the PR, right next
        to any other CI jobs.
        """
        repo_name, pr_number = self._parse_pr_url(pr_url)
        pr_details = self.github.get_pr_details(repo_name, pr_number)
        self.github.set_commit_status(
            repo_name=repo_name,
            sha=pr_details["head_sha"],
            state=state,
            description=description,
            context=context,
            target_url=target_url,
        )

    @staticmethod
    def _parse_pr_url(url: str) -> tuple[Optional[str], Optional[int]]:
        try:
            parts = url.rstrip('/').split('/')
            pr_number = int(parts[-1])
            repo_name = '/'.join(parts[-4:-2])
            return repo_name, pr_number
        except (IndexError, ValueError):
            return None, None
    def push_generated_tests(self, pr_url: str, test_files: list[str]) -> None:
        """Push generated test files back to the PR's head branch."""
        repo_name, pr_number = self._parse_pr_url(pr_url)
        pr_details = self.github.get_pr_details(repo_name, pr_number)
        branch = pr_details["head_branch"]

        for file_path in test_files:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.github.push_file(
                repo_name=repo_name,
                branch=branch,
                file_path=file_path.replace("\\", "/"),  # normalize Windows paths
                content=content,
                commit_message="chore: add AI-generated tests",
            )