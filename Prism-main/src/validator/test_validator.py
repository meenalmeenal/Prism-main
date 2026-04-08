# In src/validator/test_validator.py
from typing import Any, Dict, List, Optional, Tuple
import logging
import json
import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

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
    """

    def __init__(self):
        """Initialize the test validator."""
        # Align required fields with the structures produced by the generators:
        #  - title: human‑readable name
        #  - steps: ordered list of step dicts
        #  - priority: P1/P2/P3 style priority
        self.required_fields = ["title", "steps", "priority"]
        self.valid_priorities = ["P1", "P2", "P3"]
        self.valid_statuses = ["Draft", "Active", "Inactive"]
        
    def validate_test_case(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single test case.
        
        Args:
            test_case: Test case dictionary to validate
            
        Returns:
            Dictionary with validation results
        """
        errors = []
        
        # Check required fields
        for field in self.required_fields:
            if field not in test_case:
                errors.append(f"Missing required field: {field}")
                
        # Check steps format if present
        if "steps" in test_case and not isinstance(test_case["steps"], list):
            errors.append("Steps must be a list")
            
        # Check priority if present
        if "priority" in test_case and test_case["priority"] not in self.valid_priorities:
            errors.append(f"Invalid priority. Must be one of: {', '.join(self.valid_priorities)}")
            
        # Check status if present
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
        """Validate multiple test cases.
        
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
        """Validate a list of test cases.

        This provides the `(validated_cases, stats)` interface expected by
        :func:`src.pipeline.pipeline_runner.run_pipeline`.
        """

        validated_cases: List[Dict[str, Any]] = []

        for tc in test_cases:
            result = self.validate_test_case(tc)
            if result["is_valid"]:
                validated_cases.append(tc)

        stats: Dict[str, Any] = {
            "total_input": len(test_cases),
            "total_output": len(validated_cases),
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