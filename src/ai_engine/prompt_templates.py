# src/ai_engine/prompt_templates.py
"""
Prompt templates for AI test case generation.
This file contains all prompt engineering logic separated from AI client code.
"""

from typing import List, Dict


class PromptTemplates:
    """Centralized prompt templates for test case generation"""
    
    @staticmethod
    def get_test_generation_prompt(
        issue_key: str, 
        summary: str, 
        acceptance_criteria: List[str]
    ) -> str:
        """
        Build the main prompt for generating test cases from acceptance criteria.
        
        Args:
            issue_key: Jira issue key (e.g., "ZT-3")
            summary: Issue summary/title
            acceptance_criteria: List of acceptance criteria strings
            
        Returns:
            Complete prompt string for the AI model
        """
        
        # Format acceptance criteria as numbered list
        acs_text = "\n".join([f"{i}. {ac}" for i, ac in enumerate(acceptance_criteria, 1)])
        
        # Build the complete prompt
        prompt = f"""You are an expert QA engineer specializing in test case design. Your task is to generate comprehensive, detailed test cases for a software feature.

**Story Information:**
- Issue Key: {issue_key}
- Feature Summary: {summary}

**Acceptance Criteria:**
{acs_text}

**Your Task:**
Generate 8-10 detailed test cases that thoroughly cover the acceptance criteria above. Include:

1. **Positive Test Cases (2 cases)**: Happy path scenarios where everything works as expected
2. **Negative Test Cases (2-3 cases)**: Error handling, invalid inputs, failure scenarios
3. **Boundary Test Cases (1-2 cases)**: Edge cases, limits, special values (min/max lengths, special characters)
4. **UI Validation Test Cases (1 case)**: Field validation, button states, form behavior, disabled/enabled states
5. **Risk-Based Test Cases (2 cases)**: Security risks (SQL injection, XSS), authentication failures, session handling, data integrity issues

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
                        "pattern": "^[A-Z]+-[0-9]+-TC-[0-9]{3}-(POSITIVE|NEGATIVE|BOUNDARY|UI_VALIDATION)$"
                    },
                    "title": {
                        "type": "string",
                        "minLength": 10
                    },
                    "type": {
                        "type": "string",
                        "enum": ["positive", "negative", "boundary", "ui_validation"]
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