# src/integrations/github_client.py
import os
from typing import Dict, Optional

from github import Github, GithubException, Auth

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
                "head_branch": pr.head.ref
            }
        except GithubException as e:
            raise Exception(f"GitHub API error: {e}")

    @staticmethod
    def extract_issue_key(pr_title: str, pr_body: str) -> Optional[str]:
        """Extract Jira issue key from PR title or body."""
        import re
        # Look for patterns like "PROJ-123" in title or body
        for text in [pr_title, pr_body]:
            match = re.search(r'([A-Z]+-\d+)', text)
            if match:
                return match.group(1)
        return None