# src/feedback/feedback_store.py
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

@dataclass
class TestFeedback:
    __test__ = False
    test_case_id: str
    issue_key: str
    error_message: str
    test_steps: List[Dict]
    timestamp: str
    resolved: bool = False
    resolved_at: Optional[str] = None
    title: str = ""

class FeedbackStore:
    def __init__(self, storage_path: str = "data/feedback.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: List[Dict] = self._load_data()

    def _load_data(self) -> List[Dict]:
        if self.storage_path.exists():
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def _save_data(self):
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=2)

    def add_feedback(self, feedback: TestFeedback) -> None:
        self._data.append(asdict(feedback))
        self._save_data()

    def mark_resolved(self, test_case_id: str, resolved_at: Optional[str] = None) -> bool:
        """Mark stored failure record(s) for a test case as resolved."""
        matched = False
        from datetime import datetime
        ts = resolved_at or datetime.now().isoformat()
        for item in self._data:
            if item.get("test_case_id") == test_case_id:
                matched = True
                item["resolved"] = True
                item["resolved_at"] = ts
        if matched:
            self._save_data()
        return matched

    def get_feedback_for_issue(self, issue_key: str, include_resolved: bool = False) -> List[TestFeedback]:
        results = []
        for item in self._data:
            if item.get("issue_key") == issue_key:
                if include_resolved or not item.get("resolved", False):
                    results.append(TestFeedback(
                        test_case_id=item.get("test_case_id", ""),
                        issue_key=item.get("issue_key", ""),
                        error_message=item.get("error_message", ""),
                        test_steps=item.get("test_steps", []),
                        timestamp=item.get("timestamp", ""),
                        resolved=item.get("resolved", False),
                        resolved_at=item.get("resolved_at"),
                        title=item.get("title", ""),
                    ))
        return results
