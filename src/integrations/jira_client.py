"""Jira integration client.

Responsible for fetching Jira issue details and returning normalized
issue data suitable for the AI test generator.

The client supports two modes:
- Real HTTP calls using Jira's REST API when credentials are available
- A deterministic mock response when credentials are missing or HTTP
  requests are unavailable
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


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
    """Simple Jira REST client with graceful mocking.

    Configuration is read from environment variables by default:

    - JIRA_BASE_URL   (e.g. https://your-domain.atlassian.net)
    - JIRA_EMAIL      (account e-mail / username)
    - JIRA_API_TOKEN  (API token for basic auth)

    If any of these are missing, the client falls back to a
    deterministic mock response so the rest of the pipeline can run
    without live Jira access.
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

        self._requests = None
        if self.base_url and self.email and self.api_token:
            try:
                import requests  # type: ignore[import]

                self._requests = requests
                logger.info("JiraClient initialized in LIVE mode for %s", self.base_url)
            except ImportError:  # pragma: no cover - environment-specific
                logger.warning("requests not installed; JiraClient will run in MOCK mode")
        else:
            logger.info("JiraClient initialized in MOCK mode (missing credentials)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_issue(self, issue_key: str) -> NormalizedIssue:
        """Fetch and normalize a Jira issue.

        When Jira credentials or HTTP support are unavailable, a mocked
        issue is returned instead so that the pipeline can still be
        executed end-to-end.
        """

        if not self._requests or not (self.base_url and self.email and self.api_token):
            logger.info("Using mocked Jira issue for key %s", issue_key)
            return self._mock_issue(issue_key)

        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        auth = (self.email, self.api_token)
        headers = {"Accept": "application/json"}

        try:
            response = self._requests.get(url, headers=headers, auth=auth, timeout=10)
            if response.status_code != 200:
                logger.warning(
                    "Jira API returned status %s for %s; falling back to mock",
                    response.status_code,
                    issue_key,
                )
                return self._mock_issue(issue_key)

            data = response.json()
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Error calling Jira API (%s); falling back to mock", exc)
            return self._mock_issue(issue_key)

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

    def _mock_issue(self, issue_key: str) -> NormalizedIssue:
        """Return a deterministic mock issue for offline development."""

        summary = "User can log in using valid credentials"
        description = (
            "As a registered user, I want to log into the system using my "
            "email and password so that I can access my dashboard."
        )
        acceptance_criteria = [
            "Given a valid user account, when correct credentials are provided, then the user is logged in successfully.",
            "Given an invalid password, an appropriate error message is shown and the user is not logged in.",
            "Account lockout is triggered after 5 consecutive failed login attempts.",
        ]

        return NormalizedIssue(
            issue_key=issue_key,
            summary=summary,
            description=description,
            acceptance_criteria=acceptance_criteria,
        )


__all__ = ["JiraClient", "NormalizedIssue"]
