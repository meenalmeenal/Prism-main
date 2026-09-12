"""Feedback loop module.

Learns from test execution results and defects to improve AI generation.
"""

from src.feedback.feedback_store import FeedbackStore, TestFeedback
from src.feedback.feedback_analyzer import FeedbackAnalyzer
from src.feedback.feedback_loop import FeedbackLoop

__all__ = ["FeedbackStore", "TestFeedback", "FeedbackAnalyzer", "FeedbackLoop"]
