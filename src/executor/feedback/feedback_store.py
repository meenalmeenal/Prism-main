# src/feedback/feedback_store.py
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

@dataclass
class TestFeedback:
    test_case_id: str
    issue_key: str
    error_message: str
    test_steps: List[Dict]
    timestamp: str
    resolved: bool = False

class FeedbackStore:
    def __init__(self, storage_path: str = "data/feedback.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._data: List[Dict] = self._load_data()

    def _load_data(self) -> List[Dict]:
        if self.storage_path.exists():
            with open(self.storage_path, 'r') as f:
                return json.load(f)
        return []

    def _save_data(self):
        with open(self.storage_path, 'w') as f:
            json.dump(self._data, f, indent=2)

    def add_feedback(self, feedback: TestFeedback) -> None:
        self._data.append(asdict(feedback))
        self._save_data()

    def get_feedback_for_issue(self, issue_key: str) -> List[TestFeedback]:
        return [TestFeedback(**item) for item in self._data 
               if item["issue_key"] == issue_key and not item["resolved"]]