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
                    "head_branch": pr_details["head_branch"]
                }
            }
        except Exception as e:
            raise Exception(f"Failed to process PR: {str(e)}")

    @staticmethod
    def _parse_pr_url(url: str) -> tuple[Optional[str], Optional[int]]:
        try:
            parts = url.rstrip('/').split('/')
            pr_number = int(parts[-1])
            repo_name = '/'.join(parts[-4:-2])
            return repo_name, pr_number
        except (IndexError, ValueError):
            return None, None