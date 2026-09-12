# In src/validator/test_validator.py
from typing import Any, Dict, List, Optional, Tuple
import logging
import json
import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

try:
    import jsonschema
except ImportError:  # pragma: no cover - optional dependency
    jsonschema = None  # type: ignore[assignment]

from src.ai_engine.prompt_templates import PromptTemplates

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of test case validation."""
    is_valid: bool
    message: str
    test_case: Dict[str, Any]
    errors: List[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "is_valid": self.is_valid,
            "message": self.message,
            "test_case": self.test_case,
            "errors": self.errors or []
        }


class TestValidator:
    """Validates test cases against a set of rules.

    NOTE: This validator is intentionally lightweight so it can work with
    both AI‑generated and rule‑based test cases produced by the pipeline.

    It performs three layers of checking:
      1. Structural JSON Schema validation (PromptTemplates.get_json_schema()).
      2. Lightweight field/enum checks (kept as a safety net in case the
         schema check is skipped, e.g. jsonschema not installed).
      3. Near-duplicate title detection (_is_similar_title), so that
         semantically-repeated test cases from either generator are
         dropped before publishing to Zephyr.
    """

    def __init__(self, similarity_threshold: float = 0.8):
        """Initialize the test validator."""
        # Align required fields with the structures produced by the generators:
        #  - title: human‑readable name
        #  - steps: ordered list of step dicts
        #  - priority: P1/P2/P3 style priority
        self.required_fields = ["title", "steps", "priority"]
        self.valid_priorities = ["P1", "P2", "P3"]
        self.valid_statuses = ["Draft", "Active", "Inactive"]
        self.valid_types = ["positive", "negative", "boundary", "ui_validation", "risk_based"]

        self.similarity_threshold = similarity_threshold

        # Cache the JSON schema for individual test case items.
        try:
            self._schema = PromptTemplates.get_json_schema()["items"]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not load JSON schema from PromptTemplates: {exc}")
            self._schema = None

        if jsonschema is None:
            logger.warning(
                "Package 'jsonschema' is not installed. Schema validation will be "
                "skipped and only lightweight field checks will run. "
                "Install with: pip install jsonschema"
            )

    # ------------------------------------------------------------------
    # Duplicate detection
    # ------------------------------------------------------------------

    def _is_similar_title(self, title_a: str, title_b: str) -> bool:
        """Return True if two titles are near-duplicates.

        Uses two complementary signals so we catch both "same words,
        different order" and "same phrasing, minor rewording" cases:

        - Word-overlap ratio: |A ∩ B| / max(|A|, |B|)
        - Sequence similarity ratio (difflib.SequenceMatcher)

        A title pair is flagged as similar if either signal is at or
        above ``self.similarity_threshold`` (default 0.8).
        """
        if not title_a or not title_b:
            return False

        a_words = set(title_a.lower().split())
        b_words = set(title_b.lower().split())
        if not a_words or not b_words:
            return False

        overlap_ratio = len(a_words & b_words) / max(len(a_words), len(b_words))
        seq_ratio = SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio()

        return overlap_ratio >= self.similarity_threshold or seq_ratio >= self.similarity_threshold

    # ------------------------------------------------------------------
    # Single test case validation
    # ------------------------------------------------------------------

    def validate_test_case(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single test case.

        Args:
            test_case: Test case dictionary to validate

        Returns:
            Dictionary with validation results
        """
        errors = []

        # --- Layer 1: structural JSON Schema validation -------------------
        if jsonschema is not None and self._schema is not None:
            try:
                jsonschema.validate(instance=test_case, schema=self._schema)
            except jsonschema.ValidationError as e:
                errors.append(f"Schema validation failed: {e.message}")
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"jsonschema check raised unexpected error, skipping: {e}")

        # --- Layer 2: lightweight field / enum checks (safety net) --------
        for field in self.required_fields:
            if field not in test_case:
                errors.append(f"Missing required field: {field}")

        if "steps" in test_case and not isinstance(test_case["steps"], list):
            errors.append("Steps must be a list")

        if "priority" in test_case and test_case["priority"] not in self.valid_priorities:
            errors.append(f"Invalid priority. Must be one of: {', '.join(self.valid_priorities)}")

        if "type" in test_case and test_case["type"] not in self.valid_types:
            errors.append(f"Invalid type. Must be one of: {', '.join(self.valid_types)}")

        if "status" in test_case and test_case["status"] not in self.valid_statuses:
            errors.append(f"Invalid status. Must be one of: {', '.join(self.valid_statuses)}")

        # Return validation result
        is_valid = len(errors) == 0
        return {
            "is_valid": is_valid,
            "test_case": test_case,
            "errors": errors,
        }

    def validate_test_cases(self, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Validate multiple test cases (no dedup — see validate_all for that).

        Args:
            test_cases: List of test case dictionaries to validate

        Returns:
            Dictionary with validation results
        """
        results = {
            "valid": [],
            "invalid": [],
            "summary": {
                "total": len(test_cases),
                "valid": 0,
                "invalid": 0
            }
        }

        for test_case in test_cases:
            result = self.validate_test_case(test_case)
            if result["is_valid"]:
                results["valid"].append(result)
                results["summary"]["valid"] += 1
            else:
                results["invalid"].append(result)
                results["summary"]["invalid"] += 1

        return results

    # ------------------------------------------------------------------
    # Compatibility helper for the pipeline
    # ------------------------------------------------------------------

    def validate_all(self, test_cases: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Validate a list of test cases, including near-duplicate removal.

        This provides the `(validated_cases, stats)` interface expected by
        :func:`src.pipeline.pipeline_runner.run_pipeline`.

        Cases that fail schema/field validation are dropped first. Among
        the remaining valid cases, any whose title is a near-duplicate of
        an already-accepted case's title (per ``_is_similar_title``) is
        also dropped, keeping the first occurrence.
        """

        validated_cases: List[Dict[str, Any]] = []
        dropped_invalid = 0
        dropped_duplicates = 0

        for tc in test_cases:
            result = self.validate_test_case(tc)
            if not result["is_valid"]:
                dropped_invalid += 1
                logger.info(
                    "Dropped invalid test case '%s': %s",
                    tc.get("title", "untitled")[:60],
                    "; ".join(result["errors"]),
                )
                continue

            title = tc.get("title", "")
            is_duplicate = any(
                self._is_similar_title(title, existing.get("title", ""))
                for existing in validated_cases
            )
            if is_duplicate:
                dropped_duplicates += 1
                logger.info("Dropped near-duplicate test case: %s", title[:60])
                continue

            validated_cases.append(tc)

        stats: Dict[str, Any] = {
            "total_input": len(test_cases),
            "total_output": len(validated_cases),
            "dropped_invalid": dropped_invalid,
            "dropped_duplicates": dropped_duplicates,
        }

        return validated_cases, stats

    def validate_test_case_file(self, file_path: str) -> Dict[str, Any]:
        """Validate test cases from a JSON file.

        Args:
            file_path: Path to JSON file containing test cases

        Returns:
            Dictionary with validation results
        """
        try:
            with open(file_path, 'r') as f:
                test_cases = json.load(f)

            if not isinstance(test_cases, list):
                return {
                    "is_valid": False,
                    "message": "Invalid format: Expected a list of test cases",
                    "file": file_path,
                    "test_cases": []
                }

            return {
                "is_valid": True,
                "message": f"Validated {len(test_cases)} test cases",
                "file": file_path,
                "results": self.validate_test_cases(test_cases)
            }

        except json.JSONDecodeError as e:
            return {
                "is_valid": False,
                "message": f"Invalid JSON: {str(e)}",
                "file": file_path,
                "test_cases": []
            }
        except Exception as e:
            return {
                "is_valid": False,
                "message": f"Error reading file: {str(e)}",
                "file": file_path,
                "test_cases": []
            }