# src/ai_engine/prompt_templates.py
"""
Prompt templates for AI test case generation.
This file contains all prompt engineering logic separated from AI client code.
"""

from typing import List, Dict, Optional, Any


class PromptTemplates:
    """Centralized prompt templates for test case generation"""
    
    @staticmethod
    def get_test_generation_prompt(
        issue_key: str, 
        summary: str, 
        acceptance_criteria: List[str],
        past_failures: Optional[List[Any]] = None,
        resolved_failures: Optional[List[Any]] = None,
    ) -> str:
        """
        Build the main prompt for generating test cases from acceptance criteria.
        
        Args:
            issue_key: Jira issue key (e.g., "ZT-3")
            summary: Issue summary/title
            acceptance_criteria: List of acceptance criteria strings
            past_failures: Optional list of past TestFeedback or failure dicts
            resolved_failures: Optional list of resolved TestFeedback or failure dicts
            
        Returns:
            Complete prompt string for the AI model
        """
        
        # Format acceptance criteria as numbered list
        acs_text = "\n".join([f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria, 1)])

        failures_section = ""
        if past_failures:
            recent_failures = past_failures[-10:] if len(past_failures) > 10 else past_failures
            failure_lines = []
            for f in recent_failures:
                if hasattr(f, "test_case_id") and hasattr(f, "error_message"):
                    t_val = getattr(f, "title", None)
                    title = (t_val or "").strip() or getattr(f, "test_case_id", "Test Case")
                    reason = getattr(f, "error_message", "Unknown error")
                elif isinstance(f, dict):
                    title = (f.get("title") or "").strip() or f.get("test_case_id") or "Test Case"
                    reason = f.get("error_message") or f.get("error") or f.get("reason") or "Unknown error"
                else:
                    title = "Test Case"
                    reason = str(f)
                reason_str = str(reason).strip()[:300]
                failure_lines.append(f"- {title} — failed because: {reason_str}")

            if failure_lines:
                failures_text = "\n".join(failure_lines)
                failures_section = (
                    "\n\n## Known past failures for this issue (learn from these)\n"
                    f"{failures_text}\n"
                    "Avoid regenerating these as-is. Prefer corrected steps, more precise selectors,\n"
                    "and explicit preconditions. Do not silently drop coverage these cases intended."
                )

        resolved_section = ""
        if resolved_failures:
            recent_resolved = resolved_failures[-5:] if len(resolved_failures) > 5 else resolved_failures
            resolved_lines = []
            for f in recent_resolved:
                if hasattr(f, "test_case_id") and hasattr(f, "error_message"):
                    t_val = getattr(f, "title", None)
                    title = (t_val or "").strip() or getattr(f, "test_case_id", "Test Case")
                    reason = getattr(f, "error_message", "Resolved issue")
                elif isinstance(f, dict):
                    title = (f.get("title") or "").strip() or f.get("test_case_id") or "Test Case"
                    reason = f.get("error_message") or f.get("error") or f.get("reason") or "Resolved issue"
                else:
                    title = "Test Case"
                    reason = str(f)
                reason_str = str(reason).strip()[:300]
                resolved_lines.append(f"- {title} — was failing because: {reason_str}")

            if resolved_lines:
                resolved_text = "\n".join(resolved_lines)
                resolved_section = (
                    "\n\n## Previously fixed for this issue — do not reintroduce\n"
                    f"{resolved_text}\n"
                    "Ensure new test cases preserve fixes and avoid re-triggering these resolved failure modes."
                )
        
        # Build the complete prompt
        prompt = f"""You are an expert QA engineer specializing in test case design. Your task is to generate comprehensive, detailed test cases for a software feature.

**Story Information:**
- Issue Key: {issue_key}
- Feature Summary: {summary}

**Acceptance Criteria:**
{acs_text}{failures_section}{resolved_section}

**Your Task:**
Generate 8-10 detailed test cases that thoroughly cover the acceptance criteria above. Include:

1. **Positive Test Cases (2 cases)**: Happy path scenarios where everything works as expected
2. **Negative Test Cases (2-3 cases)**: Error handling, invalid inputs, failure scenarios
3. **Boundary Test Cases (1-2 cases)**: Edge cases, limits, special values (min/max lengths, special characters)
4. **UI Validation Test Cases (1 case)**: Field validation, button states, form behavior, disabled/enabled states
5. **Risk-Based Test Cases (1-2 cases per requirement)**: Cover areas with historically high defect likelihood, critical business logic, or complex conditional paths (not just negative/edge-case input handling, which is already covered by the negative/boundary categories). This includes security risks (SQL injection, XSS), authentication failures, session handling, and data integrity issues.

**Critical Requirements:**
- Each test case MUST have complete detailed, step-by-step instructions
- Include specific, realistic test data (actual email addresses, passwords, values)
- Expected results must be precise and verifiable
- Cover EVERY acceptance criterion provided
- Test cases should be executable by any QA engineer
- Use realistic user scenarios

**Output Format:**
Return ONLY a valid JSON array. NO markdown formatting, NO code blocks, NO explanations - just pure JSON.

{PromptTemplates._get_json_schema_description(issue_key)}

{PromptTemplates._get_example_test_case(issue_key)}

**Important Instructions:**
- Start your response directly with the [ character
- End your response with the ] character
- Use double quotes for all strings
- Ensure all JSON is valid and parseable
- Do not include any text before or after the JSON array

Generate the test cases now:"""
        
        return prompt
    
    @staticmethod
    def _get_json_schema_description(issue_key: str) -> str:
        """Return the JSON schema description for test cases"""
        
        return """**Required JSON Structure:**
Each test case in the array must follow this exact structure:

```
{
  "id": "string - Format: '[ISSUE_KEY]-TC-[NUMBER]-[TYPE]' (e.g., 'ZT-3-TC-001-POSITIVE')",
  "title": "string - Clear, descriptive test case title",
  "description": "string - 2-4 sentence summary of what this test verifies and why, written for a Zephyr 'Description' field",
  "type": "string - One of: 'positive', 'negative', 'boundary', 'ui_validation', 'risk_based'",
  "priority": "string - One of: 'P1' (critical), 'P2' (high), 'P3' (medium)",
  "preconditions": [
    "string - Setup/prerequisites needed before test execution"
  ],
  "steps": [
    {
      "step_number": integer - Sequential step number starting from 1,
      "action": "string - What the tester should do",
      "test_data": "string or null - Specific data to use (email, password, etc.)",
      "expected_result": "string - What should happen after this step"
    }
  ],
  "tags": [
    "string - Relevant tags (e.g., 'login', 'authentication', 'security')"
  ]
}
```"""
    
    @staticmethod
    def _get_example_test_case(issue_key: str) -> str:
        """Return an example test case for few-shot learning"""
        
        return f"""**Example Test Case (for reference):**
```json
{{
  "id": "{issue_key}-TC-001-POSITIVE",
  "title": "User successfully logs in with valid credentials",
  "description": "Verifies that a registered user can log in using a correct email and password combination, confirming the authentication flow works end-to-end for the happy path.",
  "type": "positive",
  "priority": "P1",
  "preconditions": [
    "User is on the login page",
    "User has a valid registered account",
    "Browser cookies are enabled"
  ],
  "steps": [
    {{
      "step_number": 1,
      "action": "Navigate to the login page",
      "test_data": "https://example.com/login",
      "expected_result": "Login page loads successfully with email and password fields visible"
    }},
    {{
      "step_number": 2,
      "action": "Enter valid email address in the email field",
      "test_data": "testuser@example.com",
      "expected_result": "Email field is populated with the entered email"
    }},
    {{
      "step_number": 3,
      "action": "Enter valid password in the password field",
      "test_data": "SecurePass123!",
      "expected_result": "Password field shows masked characters, login button becomes enabled"
    }},
    {{
      "step_number": 4,
      "action": "Click the login button",
      "test_data": null,
      "expected_result": "User is redirected to dashboard page, welcome message displays with user's name"
    }},
    {{
      "step_number": 5,
      "action": "Verify user session is established",
      "test_data": null,
      "expected_result": "User profile icon is visible in header, logout option is available"
    }}
  ],
  "tags": ["login", "authentication", "positive-flow", "user-access"]
}}
```"""
    
    @staticmethod
    def get_json_schema() -> Dict:
        """
        Return the JSON schema for validation.
        Can be used for automated validation of AI responses.
        """
        return {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title", "type", "priority", "preconditions", "steps", "tags"],
                "properties": {
                    "id": {
                        "type": "string",
                        "pattern": "^[A-Z]+-[0-9]+-TC-[0-9]{3}-(POSITIVE|NEGATIVE|BOUNDARY|UI_VALIDATION|RISK_BASED)$"
                    },
                    "title": {
                        "type": "string",
                        "minLength": 10
                    },
                    "type": {
                        "type": "string",
                        "enum": ["positive", "negative", "boundary", "ui_validation", "risk_based"]
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["P1", "P2", "P3"]
                    },
                    "preconditions": {
                        "type": "array",
                        "items": {"type": "string"}
                    },
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["step_number", "action", "expected_result"],
                            "properties": {
                                "step_number": {"type": "integer", "minimum": 1},
                                "action": {"type": "string"},
                                "test_data": {"type": ["string", "null"]},
                                "expected_result": {"type": "string"}
                            }
                        }
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        }
    
    @staticmethod
    def get_refinement_prompt(test_case: Dict, feedback: str) -> str:
        """
        Prompt for refining/improving a test case based on feedback.
        Useful for the feedback loop in Phase 7.
        
        Args:
            test_case: The original test case
            feedback: Feedback/issues found with the test case
            
        Returns:
            Prompt for refining the test case
        """
        
        return f"""You are a QA expert. A test case has been executed and requires improvement based on feedback.

**Original Test Case:**
```json
{test_case}
```

**Feedback/Issues:**
{feedback}

**Your Task:**
Refine the test case to address the feedback. Return the improved test case in the same JSON format.

Updated test case:"""
    
    @staticmethod
    def get_negative_test_generation_prompt(
        issue_key: str,
        summary: str,
        positive_test: Dict
    ) -> str:
        """
        Generate negative test cases based on a positive test.
        
        Args:
            issue_key: Jira issue key
            summary: Issue summary
            positive_test: A positive test case to derive negative tests from
            
        Returns:
            Prompt for generating related negative tests
        """
        
        return f"""You are a QA expert. Given a positive test case, generate corresponding negative test cases.

**Feature:** {issue_key} - {summary}

**Positive Test Case:**
```json
{positive_test}
```

**Your Task:**
Generate 2-3 negative test cases that test failure scenarios related to the positive test above.
Consider: invalid inputs, missing data, unauthorized access, boundary violations, etc.

Return as a JSON array following the same structure as the example.

Negative test cases:"""