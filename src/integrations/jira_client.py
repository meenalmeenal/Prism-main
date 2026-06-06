"""Jira integration client.

Responsible for fetching Jira issue details and returning normalized
issue data suitable for the AI test generator.

Requires JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN to be set
in the environment (.env). Raises RuntimeError on any auth or
connection failure — no mock fallback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv(override=True)


@dataclass
class NormalizedIssue:
    """Normalized issue shape consumed by AITestGenerator.

    Fields are intentionally minimal and stable.
    """

    issue_key: str
    summary: str
    description: str
    acceptance_criteria: list[str]


class JiraClient:
    """Jira REST client.

    Configuration is read from environment variables:

    - JIRA_BASE_URL   (e.g. https://your-domain.atlassian.net)
    - JIRA_EMAIL      (account e-mail / username)
    - JIRA_API_TOKEN  (API token from id.atlassian.com)

    Raises RuntimeError on missing credentials or API failures.
    No mock fallback.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("JIRA_BASE_URL", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")

        try:
            import requests  # type: ignore[import]
            self._requests = requests
            logger.info("JiraClient initialized for %s", self.base_url)
        except ImportError:
            raise RuntimeError(
                "The 'requests' package is not installed. Run: pip install requests"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_issue(self, issue_key: str) -> NormalizedIssue:
        """Fetch and normalize a Jira issue.

        Raises RuntimeError if credentials are missing or if the Jira API
        returns a non-200 response, so failures are visible immediately
        rather than silently generating mock data.
        """

        if not self._requests:
            raise RuntimeError(
                "Jira credentials are missing or incomplete. "
                "Please set JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in your .env file."
            )

        if not (self.base_url and self.email and self.api_token):
            raise RuntimeError(
                "One or more Jira credentials are empty. "
                "Check JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN in your .env file."
            )

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        auth = (self.email, self.api_token)
        headers = {"Accept": "application/json"}

        logger.info("Fetching Jira issue from: %s", url)
        logger.info("Auth email: %s | Token length: %d", self.email, len(self.api_token))

        try:
            response = self._requests.get(url, headers=headers, auth=auth, timeout=10)
        except Exception as exc:
            raise RuntimeError(
                f"Network error while connecting to Jira ({self.base_url}): {exc}\n"
                "Check your JIRA_BASE_URL and internet connection."
            ) from exc

        if response.status_code == 401:
            raise RuntimeError(
                f"Jira authentication failed (401) for {url}.\n"
                "Your JIRA_EMAIL or JIRA_API_TOKEN is incorrect.\n"
                "Generate a new token at: https://id.atlassian.com/manage-profile/security/api-tokens"
            )

        if response.status_code == 403:
            raise RuntimeError(
                f"Jira access forbidden (403) for {url}.\n"
                "Your account does not have permission to read this issue."
            )

        if response.status_code == 404:
            raise RuntimeError(
                f"Jira issue '{issue_key}' not found (404).\n"
                f"URL attempted: {url}\n"
                f"Jira response body: {response.text[:500]}\n\n"
                "Possible causes:\n"
                "  1. The issue key does not exist in your Jira project.\n"
                "  2. Your API token is wrong — Jira returns 404 for bad auth on some endpoints.\n"
                "     -> Regenerate at: https://id.atlassian.com/manage-profile/security/api-tokens\n"
                "  3. Your JIRA_BASE_URL is wrong (e.g. missing subdomain).\n"
                f"     -> Current value: {self.base_url}"
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"Jira API returned unexpected status {response.status_code} for '{issue_key}'.\n"
                f"URL: {url}\n"
                f"Response body: {response.text[:500]}"
            )

        data = response.json()
        return self._normalize_issue(issue_key, data)

    # ------------------------------------------------------------------
    # Normalization & mocking helpers
    # ------------------------------------------------------------------

    def _normalize_issue(self, issue_key: str, payload: Dict[str, Any]) -> NormalizedIssue:
        fields: Dict[str, Any] = payload.get("fields", {})

        summary = str(fields.get("summary") or "")

        # Jira Cloud often stores description in Atlassian Document Format.
        # For simplicity we coerce to a plain string representation.
        description_raw = fields.get("description")
        description = self._extract_text(description_raw)

        acceptance_criteria = self._extract_acceptance_criteria(fields, description)

        logger.info(
            "Normalized Jira issue %s (summary length=%d, %d criteria)",
            issue_key,
            len(summary),
            len(acceptance_criteria),
        )

        return NormalizedIssue(
            issue_key=issue_key,
            summary=summary,
            description=description,
            acceptance_criteria=acceptance_criteria,
        )

    def _extract_text(self, value: Any) -> str:
        """Best-effort conversion of Jira field value to plain text."""

        if value is None:
            return ""

        # If this is already a string, just return it.
        if isinstance(value, str):
            return value

        # For Atlassian Document Format structures, we do a naive
        # traversal and join paragraph texts. This keeps us independent
        # from Jira's exact structure and keeps the code robust.
        try:
            if isinstance(value, dict) and value.get("content"):
                texts: list[str] = []

                def walk(node: Any) -> None:
                    if isinstance(node, dict):
                        if node.get("type") == "text" and "text" in node:
                            texts.append(str(node["text"]))
                        for child in node.get("content", []):
                            walk(child)
                    elif isinstance(node, list):
                        for item in node:
                            walk(item)

                walk(value)
                if texts:
                    return "\n".join(texts)
        except Exception:  # pragma: no cover - defensive
            pass

        # Fallback to string conversion
        return str(value)

    def _extract_acceptance_criteria(self, fields: Dict[str, Any], description: str) -> list[str]:
        """Try to infer acceptance criteria from Jira fields.

        Strategy:
        1. Look for any custom field whose name suggests acceptance
           criteria ("acceptance" or "criteria" in key).
        2. If not found, attempt to parse bullet-like lines from the
           description (lines starting with -, *, or numbered lists).
        """

        # 1) Custom fields
        for key, value in fields.items():
            key_lower = str(key).lower()
            if "acceptance" in key_lower or "criteria" in key_lower:
                criteria = self._coerce_criteria_value(value)
                if criteria:
                    return criteria

        # 2) Parse description as a fallback
        lines = [ln.strip() for ln in description.splitlines()]
        bullets: list[str] = []
        for line in lines:
            if not line:
                continue
            if line.startswith(("- ", "* ")):
                bullets.append(line[2:].strip())
            elif any(line.lower().startswith(prefix) for prefix in ["ac ", "ac1", "1.", "2."]):
                # Very light-weight heuristic for common AC formats
                bullets.append(line.split(" ", 1)[-1].strip())

        # Ensure unique & non-empty
        seen = set()
        result: list[str] = []
        for item in bullets:
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

        return result

    def _coerce_criteria_value(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            return [ln.strip(" -*\t") for ln in value.splitlines() if ln.strip(" -*\t")]
        return [str(value)]


__all__ = ["JiraClient", "NormalizedIssue"]
