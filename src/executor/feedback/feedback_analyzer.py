# src/feedback/feedback_analyzer.py
from typing import List, Dict
from dataclasses import dataclass
from .feedback_store import FeedbackStore, TestFeedback

class FeedbackAnalyzer:
    def __init__(self, store: FeedbackStore):
        self.store = store

    def analyze_failure(self, test_case: Dict, error_message: str) -> List[Dict]:
        """Analyze test failure and suggest improvements."""
        similar_failures = self._find_similar_failures(test_case, error_message)
        return self._generate_improvements(similar_failures)

    def _find_similar_failures(self, test_case: Dict, error_message: str) -> List[TestFeedback]:
        # Simple implementation - can be enhanced with NLP
        issue_key = test_case.get("issue_key")
        if not issue_key:
            return []
            
        return [
            fb for fb in self.store.get_feedback_for_issue(issue_key)
            if error_message.lower() in fb.error_message.lower()
        ]

    def _generate_improvements(self, similar_failures: List[TestFeedback]) -> List[Dict]:
        if not similar_failures:
            return []
            
        # Group by error type and suggest improvements
        error_groups = {}
        for fb in similar_failures:
            error_groups.setdefault(fb.error_message, []).append(fb)
        
        return [{
            "error": error,
            "occurrences": len(feedbacks),
            "suggested_fix": self._suggest_fix(error, feedbacks)
        } for error, feedbacks in error_groups.items()]

    def _suggest_fix(self, error: str, feedbacks: List[TestFeedback]) -> str:
        # Simple suggestion logic - can be enhanced
        return "Check if the test environment is properly set up and all dependencies are available."