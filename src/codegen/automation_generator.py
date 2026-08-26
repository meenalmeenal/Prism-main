"""Automation code generator for test cases.

Converts validated test cases into executable automation scripts
for Nightwatch.js, Playwright, and Cypress frameworks.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class AutomationGenerator:
    """Generates automation test scripts from validated test cases."""

    SUPPORTED_FRAMEWORKS = ["nightwatch", "playwright", "cypress", "gherkin"]

    def __init__(self, framework: str = "playwright", output_dir: str = "generated_tests"):
        """Initialize the automation generator.

        Parameters
        ----------
        framework: str
            Target framework: 'nightwatch', 'playwright', or 'cypress'
        output_dir: str
            Directory to write generated test files
        """
        if framework.lower() not in self.SUPPORTED_FRAMEWORKS:
            raise ValueError(f"Unsupported framework: {framework}. Choose from {self.SUPPORTED_FRAMEWORKS}")

        self.framework = framework.lower()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"AutomationGenerator initialized for {self.framework}")

    def generate_from_test_cases(
        self,
        test_cases: List[Dict[str, Any]],
        issue_key: str,
        base_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Generate automation scripts from validated test cases.

        Parameters
        ----------
        test_cases: List[Dict[str, Any]]
            Validated test cases from TestValidator
        issue_key: str
            Jira issue key (for file naming and test organization)
        base_url: Optional[str]
            Base URL for the application under test

        Returns
        -------
        List[Dict[str, Any]]
            List of generation results with file paths and metadata
        """
        logger.info(f"Generating {self.framework} tests for {len(test_cases)} test cases (issue: {issue_key})")

        results = []
        base_url = base_url or os.getenv("APP_BASE_URL", "http://localhost:3000")

        for test_case in test_cases:
            try:
                test_id = test_case.get("id", "unknown").replace(" ", "_").replace("/", "_")  # ← MUST BE FIRST

                if self.framework == "playwright":
                    code = self._generate_playwright(test_case, issue_key, base_url)
                elif self.framework == "nightwatch":
                    code = self._generate_nightwatch(test_case, issue_key, base_url)
                elif self.framework == "cypress":
                    code = self._generate_cypress(test_case, issue_key, base_url)
                else:  # gherkin
                    code = self._generate_gherkin(test_case, issue_key)

                ext = "feature" if self.framework == "gherkin" else "spec.js"
                filename = f"{issue_key}_{test_id}.{ext}"
                filepath = self.output_dir / filename

                with filepath.open("w", encoding="utf-8") as f:
                    f.write(code)

                results.append({
                    "test_case_id": test_case.get("id"),
                    "file_path": str(filepath),
                    "framework": self.framework,
                    "status": "generated",
                })

                logger.info(f"Generated {self.framework} test: {filepath}")

            except Exception as exc:
                logger.error(f"Failed to generate automation for {test_case.get('id')}: {exc}")
                results.append({
                    "test_case_id": test_case.get("id"),
                    "status": "failed",
                    "error": str(exc),
                })

        logger.info(f"Generated {len([r for r in results if r['status'] == 'generated'])}/{len(test_cases)} automation scripts")
        return results

    def _generate_playwright(self, test_case: Dict[str, Any], issue_key: str, base_url: str) -> str:
        """Generate Playwright test script."""
        test_id = test_case.get("id", "unknown")
        title = test_case.get("title", "Untitled Test")
        test_type = test_case.get("type", "positive")
        priority = test_case.get("priority", "P3")
        steps = test_case.get("steps", [])
        preconditions = test_case.get("preconditions", [])
        tags = test_case.get("tags", [])

        # Build test code
        lines = [
            "import { test, expect } from '@playwright/test';",
            "",
            f"// Auto-generated test case for {issue_key}",
            f"// Test ID: {test_id}",
            f"// Type: {test_type}, Priority: {priority}",
            "",
            f"const baseUrl = process.env.APP_BASE_URL || '{base_url}';",
            "",
            f"test.describe({json.dumps(f'{issue_key}: {title[:60]}')}, () => {{",
        ]

        # Resolve target URL path based on keywords in title, preconditions, or step definitions
        target_path = ""
        combined_text = (title + " " + " ".join(preconditions) + " " + " ".join(str(s.values()) for s in steps)).lower()
        for path in ["/boundary-test", "/reset-password", "/reset-confirm", "/register", "/dashboard"]:
            if path in combined_text:
                target_path = path
                break

        # Add preconditions as setup
        lines.append("  test.beforeEach(async ({ page }) => {")
        lines.append(f"    await page.goto(baseUrl + {json.dumps(target_path)});")
        if preconditions:
            for precond in preconditions:
                lines.append(f"    // Precondition: {precond}")
        lines.append("  });")
        lines.append("")

        # Generate test steps
        test_name_literal = json.dumps(title[:80])
        lines.append(f"  test({test_name_literal}, async ({{ page }}) => {{")

        for step in steps:
            step_num = step.get("step_number", 0)
            action = step.get("action", "")
            test_data = step.get("test_data")
            expected = step.get("expected_result", "")

            lines.append(f"    // Step {step_num}: {action}")
            if expected:
                lines.append(f"    // Expected: {expected}")

            # 1. Convert action to Playwright code
            playwright_code = self._action_to_playwright(action, test_data, expected)

            # 2. Convert expected state to Playwright assertion
            assertion_code = self._expected_to_playwright_assertion(expected, action, test_data, title)

            # 3. Output action and/or assertion code
            if playwright_code:
                action_lower = action.lower()
                is_action_boilerplate = any(bp in action_lower for bp in ["perform the primary", "attempt to violate", "execute the operation", "identify boundary", "inject high-risk", "trigger complex"])
                is_pure_verification = not is_action_boilerplate and any(word in action_lower for word in ["verify", "check", "assert", "expect", "should"])

                if is_pure_verification:
                    if assertion_code:
                        lines.append(f"    {assertion_code}")
                    else:
                        lines.append(f"    {playwright_code}")
                else:
                    lines.append(f"    {playwright_code}")
                    if assertion_code:
                        lines.append(f"    {assertion_code}")
            elif assertion_code:
                lines.append(f"    {assertion_code}")

        lines.append("  });")
        lines.append("});")

        return "\n".join(lines)

    def _expected_to_playwright_assertion(self, expected: str, action: str, test_data: Optional[str], test_title: str = "") -> Optional[str]:
        """Convert natural language expected result into auto-retrying Playwright assertion."""
        if not expected:
            return None

        expected_lower = expected.lower()
        test_title_lower = test_title.lower()

        is_login = "login" in test_title_lower
        is_register = "register" in test_title_lower or "create an account" in test_title_lower
        is_reset_password = "reset-password" in test_title_lower or "reset password" in test_title_lower
        is_reset_confirm = "reset-confirm" in test_title_lower or "set new password" in test_title_lower
        is_positive = "successful" in test_title_lower or "accepts valid" in test_title_lower

        # Positive flow outcomes verification
        if is_positive and ("no error" in expected_lower or "observable outcome" in expected_lower or "align with" in expected_lower):
            if is_login:
                return "await expect(page).toHaveURL(/.*dashboard.*/);\n    await expect(page.locator('#welcome-msg')).toBeVisible();"
            elif is_register:
                return "await expect(page).toHaveURL(/.*\\/$/);\n    await expect(page.locator('#global-success')).toContainText(/Registration successful|confirmation email/i);"
            elif is_reset_password:
                return "await expect(page.locator('#global-success')).toContainText(/reset link/i);"
            elif is_reset_confirm:
                return "await expect(page).toHaveURL(/.*\\/$/);\n    await expect(page.locator('#reset-success')).toBeVisible();"

        # 0. Check for generic / boilerplate phrases first to avoid false-positive text assertions
        if "no error" in expected_lower or "no errors" in expected_lower:
            return "await expect(page.locator('#global-error, .error-msg').first()).toBeHidden();"

        if "relevant ui or api endpoint is available" in expected_lower or "feature can be accessed" in expected_lower:
            return "await expect(page.locator('body')).toBeVisible();"

        if "align with the business expectation" in expected_lower or "behaves exactly as described" in expected_lower:
            return "await expect(page.locator('body')).toBeVisible();"

        if "rejects the input gracefully" in expected_lower or "helpful feedback" in expected_lower or "errors are logged appropriately" in expected_lower or "safely sanitizes or rejects" in expected_lower or "avoiding security risks" in expected_lower:
            return "await expect(page.locator('#global-error, .error-msg, [role=\"alert\"]').first()).toBeVisible();"

        # 1. Check for specific page / redirect / URL states
        if "redirected to dashboard" in expected_lower or "dashboard page loads" in expected_lower or "logged in" in expected_lower:
            return "await expect(page).toHaveURL(/.*dashboard.*/);\n    await expect(page.locator('#welcome-msg')).toBeVisible();"
        if "login page" in expected_lower or "redirected to login" in expected_lower or "back to login" in expected_lower:
            return "await expect(page).toHaveURL(/.*\\/$/);\n    await expect(page.locator('#login-btn')).toBeVisible();"
        if "register page" in expected_lower or "create an account" in expected_lower:
            return "await expect(page).toHaveURL(/.*register.*/);\n    await expect(page.locator('#register-btn')).toBeVisible();"
        if "reset password page" in expected_lower or "reset-password page" in expected_lower:
            return "await expect(page).toHaveURL(/.*reset-password.*/);\n    await expect(page.locator('#send-reset-btn')).toBeVisible();"
        if "set new password" in expected_lower or "reset-confirm page" in expected_lower or "reset confirm page" in expected_lower:
            return "await expect(page).toHaveURL(/.*reset-confirm.*/);\n    await expect(page.locator('#reset-btn')).toBeVisible();"
        if "boundary test page" in expected_lower or "boundary-test page" in expected_lower:
            return "await expect(page).toHaveURL(/.*boundary-test.*/);\n    await expect(page.locator('#boundary-form')).toBeVisible();"

        # 2. Check for form field error messages (Negative & Boundary paths)
        error_keywords = ["error", "invalid", "fail", "reject", "lockout", "required", "do not match", "too long", "missing"]
        if any(kw in expected_lower for kw in error_keywords):
            if "email" in expected_lower:
                if "required" in expected_lower:
                    return "await expect(page.locator('#email-error')).toContainText(/email is required/i);"
                elif "format" in expected_lower or "invalid" in expected_lower:
                    return "await expect(page.locator('#email-error, #global-error').first()).toContainText(/invalid email format/i);"
                elif "too long" in expected_lower or "length" in expected_lower:
                    return "await expect(page.locator('#email-error, #global-error').first()).toContainText(/too long|length/i);"
                elif "already registered" in expected_lower:
                    return "await expect(page.locator('#global-error')).toContainText(/already registered/i);"

            if "password" in expected_lower:
                if "required" in expected_lower:
                    return "await expect(page.locator('#password-error')).toContainText(/password is required/i);"
                elif "least 8 characters" in expected_lower or "characters long" in expected_lower:
                    return "await expect(page.locator('#password-error, #global-error').first()).toContainText(/at least 8 characters/i);"
                elif "match" in expected_lower or "confirm" in expected_lower:
                    return "await expect(page.locator('#match-error, #global-error, .error-msg').first()).toContainText(/do not match/i);"

            if "name" in expected_lower and "required" in expected_lower:
                return "await expect(page.locator('#name-error')).toContainText(/name is required/i);"

            if "incorrect credentials" in expected_lower or "incorrect email" in expected_lower or "incorrect password" in expected_lower:
                return "await expect(page.locator('#global-error')).toContainText(/Incorrect.*credentials|Incorrect.*email|Incorrect.*password/i);"

            if "lockout" in expected_lower or "locked" in expected_lower:
                return "await expect(page.locator('#global-error')).toContainText(/locked|lockout/i);"

            # General/custom error text assertion using auto-retrying expect to contain text
            quotes = re.findall(r'"([^"]*)"', expected) or re.findall(r"'([^']*)'", expected)
            if quotes:
                return f"await expect(page.locator('#global-error, .error-msg, [role=\"alert\"]').first()).toContainText(/{re.escape(quotes[0])}/i);"

            words = [w for w in expected.split() if w.lower() not in ["the", "system", "rejects", "input", "gracefully", "provides", "helpful", "feedback", "user", "and"]]
            if len(words) > 1 and len(words) < 10:
                clean_msg = " ".join(words).replace("'", "\\'")
                return f"await expect(page.locator('#global-error, .error-msg, [role=\"alert\"]').first()).toContainText(/{clean_msg}/i);"

            return "await expect(page.locator('#global-error, .error-msg, [role=\"alert\"]').first()).toBeVisible();"

        # 3. Check for success messages / behaviors
        if "registration successful" in expected_lower or "confirmation email" in expected_lower:
            return "await expect(page.locator('#global-success')).toContainText(/Registration successful|confirmation email/i);"
        if "password reset link sent" in expected_lower or "reset link" in expected_lower:
            return "await expect(page.locator('#global-success')).toContainText(/reset link/i);"
        if "password reset successfully" in expected_lower:
            return "await expect(page.locator('#reset-success')).toBeVisible();"
        if "submitted: " in expected_lower or "submitted" in expected_lower:
            if "submitted: " in expected_lower:
                return "await expect(page.locator('#result')).toContainText(/Submitted:/i);"
            return "await expect(page.locator('#result')).toBeVisible();"

        # 4. Check for value checks
        if "populated" in expected_lower or "shows" in expected_lower or "has value" in expected_lower:
            if "email" in expected_lower or "username" in expected_lower:
                val = test_data or "testuser@example.com"
                return f"await expect(page.locator('#email')).toHaveValue({json.dumps(val)});"
            if "password" in expected_lower:
                return "await expect(page.locator('#password')).not.toHaveValue('');"

        # 5. Check for visibility of form fields/elements when loading a page
        if "fields visible" in expected_lower or "button becomes enabled" in expected_lower or "button visible" in expected_lower:
            assertions = []
            if "email" in expected_lower:
                assertions.append("await expect(page.locator('#email')).toBeVisible();")
            if "password" in expected_lower:
                assertions.append("await expect(page.locator('#password')).toBeVisible();")
            if "login button" in expected_lower or "login" in expected_lower:
                assertions.append("await expect(page.locator('#login-btn')).toBeVisible();")
            if assertions:
                return "\n    ".join(assertions)

        # 6. Default generic assertion
        safe_expected = expected.replace("\n", " ")
        if len(safe_expected) < 60:
            return f"await expect(page.locator('body')).toContainText({json.dumps(safe_expected)});"
        return "await expect(page.locator('body')).toBeVisible();"

    def _generate_nightwatch(self, test_case: Dict[str, Any], issue_key: str, base_url: str) -> str:
        """Generate Nightwatch.js test script."""
        test_id = test_case.get("id", "unknown")
        title = test_case.get("title", "Untitled Test")
        test_type = test_case.get("type", "positive")
        priority = test_case.get("priority", "P3")
        steps = test_case.get("steps", [])
        tags = test_case.get("tags", []) + [issue_key, test_type, priority]

        # Build test code
        lines = [
            f"// Auto-generated test case for {issue_key}",
            f"// Test ID: {test_id}",
            f"// Type: {test_type}, Priority: {priority}",
            "",
            "module.exports = {",
            f"  '@tags': {json.dumps(tags)},",
            f"  '{test_id}: {title[:60]}': function (browser) {{",
            f"    const baseUrl = process.env.APP_BASE_URL || '{base_url}';",
            "",
        ]

        # Generate test steps
        for step in steps:
            step_num = step.get("step_number", 0)
            action = step.get("action", "")
            test_data = step.get("test_data")
            expected = step.get("expected_result", "")

            lines.append(f"    // Step {step_num}: {action}")
            if expected:
                lines.append(f"    // Expected: {expected}")

            # Convert action to Nightwatch code
            nightwatch_code = self._action_to_nightwatch(action, test_data, expected)
            if nightwatch_code:
                lines.append(f"    {nightwatch_code}")

        lines.append("    browser.end();")
        lines.append("  }")
        lines.append("};")

        return "\n".join(lines)

    def _generate_cypress(self, test_case: Dict[str, Any], issue_key: str, base_url: str) -> str:
        """Generate Cypress test script."""
        test_id = test_case.get("id", "unknown")
        title = test_case.get("title", "Untitled Test")
        test_type = test_case.get("type", "positive")
        priority = test_case.get("priority", "P3")
        steps = test_case.get("steps", [])
        preconditions = test_case.get("preconditions", [])

        # Build test code
        lines = [
            f"// Auto-generated test case for {issue_key}",
            f"// Test ID: {test_id}",
            f"// Type: {test_type}, Priority: {priority}",
            "",
            f"const baseUrl = Cypress.env('APP_BASE_URL') || '{base_url}';",
            "",
            f"describe({json.dumps(f'{issue_key}: {title[:60]}')}, () => {{",
        ]

        # Add preconditions as before hook
        if preconditions:
            lines.append("  beforeEach(() => {")
            for precond in preconditions:
                lines.append(f"    // Precondition: {precond}")
            lines.append("  });")
            lines.append("")

        # Generate test
        test_name_literal = json.dumps(title[:80])
        lines.append(f"  it({test_name_literal}, () => {{")

        for step in steps:
            step_num = step.get("step_number", 0)
            action = step.get("action", "")
            test_data = step.get("test_data")
            expected = step.get("expected_result", "")

            lines.append(f"    // Step {step_num}: {action}")
            if expected:
                lines.append(f"    // Expected: {expected}")

            # Convert action to Cypress code
            cypress_code = self._action_to_cypress(action, test_data, expected)
            if cypress_code:
                lines.append(f"    {cypress_code}")

        lines.append("  });")
        lines.append("});")

        return "\n".join(lines)

    def _generate_gherkin(self, test_case: Dict[str, Any], issue_key: str) -> str:
        """Generate Gherkin .feature file from test case."""
        title = test_case.get("title", "Untitled Test")
        test_type = test_case.get("type", "positive")
        priority = test_case.get("priority", "P3")
        steps = test_case.get("steps", [])
        preconditions = test_case.get("preconditions", [])
        tags = test_case.get("tags", []) + [test_type, priority, issue_key]

        tag_line = " ".join(f"@{t.lower().replace(' ', '_')}" for t in tags)

        lines = [
            f"# Auto-generated feature file for {issue_key}",
            f"# Type: {test_type}, Priority: {priority}",
            "",
            tag_line,
            f"Feature: {title}",
            "",
        ]

        # Scenario title
        lines.append(f"  Scenario: {title}")

        # Preconditions as Given
        if preconditions:
            for i, precond in enumerate(preconditions):
                keyword = "Given" if i == 0 else "And"
                lines.append(f"    {keyword} {precond}")
        else:
            lines.append("    Given the user is on the application")

        # Steps → When/Then
        for i, step in enumerate(steps):
            action = step.get("action", "")
            expected = step.get("expected_result", "")
            test_data = step.get("test_data")

            action_line = f"{action}"
            if test_data:
                action_line += f' "{test_data}"'

            keyword = "When" if i == 0 else "And"
            lines.append(f"    {keyword} {action_line}")

            if expected:
                lines.append(f"    Then {expected}")

        lines.append("")
        return "\n".join(lines)

    def _action_to_playwright(self, action: str, test_data: Optional[str], expected: str) -> Optional[str]:
        """Convert action text to Playwright code."""
        action_lower = action.lower()
        expected_lower = expected.lower()

        # Helper boolean checks to detect current context page
        is_boundary_page = "boundary-test" in action_lower or "boundary-test" in expected_lower or "boundary test" in action_lower or "boundary test" in expected_lower
        is_register = "register" in action_lower or "register" in expected_lower
        is_reset_password = "reset-password" in action_lower or "reset password" in expected_lower or "reset-password" in expected_lower
        is_reset_confirm = "reset-confirm" in action_lower or "set new password" in expected_lower or "reset-confirm" in expected_lower

        # 0. Detect generic/boilerplate actions from RuleBasedTestGenerator and map them to real executable page actions
        if "perform the primary user action" in action_lower:
            # Positive path action mapping
            if is_register:
                import random
                rand_num = random.randint(1000, 9999)
                return (
                    "await page.locator('#name').fill('Test User');\n"
                    f"    await page.locator('#email').fill('user_{rand_num}@example.com');\n"
                    "    await page.locator('#password').fill('password123');\n"
                    "    await page.locator('#confirm-password').fill('password123');\n"
                    "    await page.locator('#register-btn').click();"
                )
            elif is_reset_password:
                return (
                    "await page.locator('#email').fill('testuser@example.com');\n"
                    "    await page.locator('#send-reset-btn').click();"
                )
            elif is_reset_confirm:
                return (
                    "await page.locator('#new-password').fill('NewPassword123!');\n"
                    "    await page.locator('#confirm-password').fill('NewPassword123!');\n"
                    "    await page.locator('#reset-btn').click();"
                )
            else:
                # Default to Login positive flow
                return (
                    "await page.locator('#email').fill('testuser@example.com');\n"
                    "    await page.locator('#password').fill('password123');\n"
                    "    await page.locator('#login-btn').click();"
                )

        if "attempt to violate the acceptance criterion" in action_lower:
            # Negative path action mapping
            if is_register:
                return (
                    "await page.locator('#name').fill('Test User');\n"
                    "    await page.locator('#email').fill('invalid-email');\n"
                    "    await page.locator('#password').fill('short');\n"
                    "    await page.locator('#confirm-password').fill('mismatch');\n"
                    "    await page.locator('#register-btn').click();"
                )
            elif is_reset_password:
                return (
                    "await page.locator('#email').fill('invalid-email');\n"
                    "    await page.locator('#send-reset-btn').click();"
                )
            elif is_reset_confirm:
                return (
                    "await page.locator('#new-password').fill('short');\n"
                    "    await page.locator('#confirm-password').fill('mismatch');\n"
                    "    await page.locator('#reset-btn').click();"
                )
            else:
                # Default to Login negative flow
                return (
                    "await page.locator('#email').fill('invalid@example.com');\n"
                    "    await page.locator('#password').fill('wrongpassword');\n"
                    "    await page.locator('#login-btn').click();"
                )

        if "inject high-risk" in action_lower or "attempt access violations" in action_lower:
            # Risk-based path action mapping
            if is_register:
                return (
                    "await page.locator('#name').fill('<script>alert(\"xss\")</script>');\n"
                    "    await page.locator('#email').fill(\"' OR '1'='1 --\");\n"
                    "    await page.locator('#password').fill('password123');\n"
                    "    await page.locator('#confirm-password').fill('password123');\n"
                    "    await page.locator('#register-btn').click();"
                )
            else:
                # Default to Login/other SQLi and XSS attempts
                return (
                    "await page.locator('#email').fill(\"' OR '1'='1 --\");\n"
                    "    await page.locator('#password').fill('<script>alert(\"xss\")</script>');\n"
                    "    await page.locator('#login-btn').click();"
                )

        if "trigger complex conditional" in action_lower:
            # Just verify we are on the page / status is OK
            return "await expect(page.locator('body')).toBeVisible();"

        if "execute the operation using each boundary value" in action_lower or "combined scenario using multiple boundary values" in action_lower:
            # Boundary path action mapping
            if is_boundary_page:
                return (
                    "await page.locator('#boundary-input').fill('a'.repeat(255));\n"
                    "    await page.locator('#boundary-form button[type=\"submit\"]').click();"
                )
            elif is_register:
                return (
                    "await page.locator('#name').fill('a'.repeat(255));\n"
                    "    await page.locator('#email').fill('email_long@example.com');\n"
                    "    await page.locator('#password').fill('password123');\n"
                    "    await page.locator('#confirm-password').fill('password123');\n"
                    "    await page.locator('#register-btn').click();"
                )
            elif is_reset_password:
                return (
                    "await page.locator('#email').fill('a'.repeat(255) + '@example.com');\n"
                    "    await page.locator('#send-reset-btn').click();"
                )
            elif is_reset_confirm:
                return (
                    "await page.locator('#new-password').fill('a'.repeat(255));\n"
                    "    await page.locator('#confirm-password').fill('a'.repeat(255));\n"
                    "    await page.locator('#reset-btn').click();"
                )
            else:
                # Login
                return (
                    "await page.locator('#email').fill('a'.repeat(255) + '@example.com');\n"
                    "    await page.locator('#password').fill('password123');\n"
                    "    await page.locator('#login-btn').click();"
                )

        if "identify boundary values" in action_lower:
            if is_boundary_page:
                return "await expect(page.locator('#boundary-form')).toBeVisible();"
            elif is_register:
                return "await expect(page.locator('#register-btn')).toBeVisible();"
            elif is_reset_password:
                return "await expect(page.locator('#send-reset-btn')).toBeVisible();"
            elif is_reset_confirm:
                return "await expect(page.locator('#reset-btn')).toBeVisible();"
            else:
                return "await expect(page.locator('#login-btn')).toBeVisible();"

        # Navigation
        if "navigate" in action_lower or "open" in action_lower or "go to" in action_lower:
            return "await page.goto(baseUrl);"

        # Click — use role/text-based selectors to avoid generic tag clicks
        if "click" in action_lower or "select" in action_lower:
            for keyword in [
                "forgot password", "reset password", "send reset", "reset link",
                "submit", "sign in", "log in", "login", "sign up", "register",
                "continue", "cancel", "back", "next", "confirm", "verify",
                "save", "delete", "edit", "update", "close", "ok",
            ]:
                if keyword in action_lower:
                    label = keyword.title()
                    return (
                        f"await page.getByRole('button', {{ name: /{label}/i }})"
                        f".or(page.getByRole('link', {{ name: /{label}/i }}))"
                        f".first().click();\n"
                        f"    await page.waitForLoadState('domcontentloaded');"
                    )
            if "button" in action_lower:
                return (
                    "await page.getByRole('button').first().click();\n"
                    "    await page.waitForLoadState('domcontentloaded');"
                )
            # Generic link — wait after to avoid context-closed errors
            return (
                "await page.getByRole('link').first().click();\n"
                "    await page.waitForLoadState('domcontentloaded');"
            )

        # Fill/Enter
        if any(word in action_lower for word in ["enter", "fill", "type", "input"]):
            if "email" in action_lower or "username" in action_lower:
                value = test_data or "testuser@example.com"
                value_literal = json.dumps(value)
                return (
                    f"await page.getByRole('textbox', {{ name: /email|username/i }})"
                    f".or(page.locator('#username, #email, input[type=email]'))"
                    f".first().fill({value_literal});"
                )
            elif "password" in action_lower:
                value = test_data or "TestPassword123!"
                value_literal = json.dumps(value)
                return (
                    f"await page.getByRole('textbox', {{ name: /password/i }})"
                    f".or(page.locator('#password, input[type=password]'))"
                    f".first().fill({value_literal});"
                )
            else:
                value = test_data or "test value"
                value_literal = json.dumps(value)
                return (
                    f"await page.locator('#boundary-input')"
                    f".or(page.locator('input[type=\"text\"], textarea'))"
                    f".first().fill({value_literal});"
                )

        # Verify/Assert
        if any(word in action_lower for word in ["verify", "check", "assert", "expect", "should"]):
            if "error" in action_lower or "message" in action_lower:
                return "await expect(page.locator('body')).toContainText(/error|invalid|message/i);"
            if "redirect" in action_lower:
                return "await page.waitForURL(/.+/, { timeout: 5000 });"
            return "await expect(page.locator('body')).toBeVisible();"

        # Wait
        if "wait" in action_lower:
            return "await page.waitForLoadState('domcontentloaded');"

        return None

    def _action_to_nightwatch(self, action: str, test_data: Optional[str], expected: str) -> Optional[str]:
        """Convert action text to Nightwatch code."""
        action_lower = action.lower()

        # Navigation
        if "navigate" in action_lower or "open" in action_lower:
            url = test_data or "/"
            return f"browser.url(baseUrl + '{url}');"

        # Click
        if "click" in action_lower:
            return "browser.click('button');"

        # Fill
        if any(word in action_lower for word in ["enter", "fill", "type"]):
            value = test_data or "test"
            value_literal = json.dumps(value)
            return f"browser.setValue('input', {value_literal});"

        # Verify
        if any(word in action_lower for word in ["verify", "check", "assert"]):
            return "browser.assert.visible('body');"

        return None

    def _action_to_cypress(self, action: str, test_data: Optional[str], expected: str) -> Optional[str]:
        """Convert action text to Cypress code."""
        action_lower = action.lower()

        # Navigation
        if "navigate" in action_lower or "open" in action_lower:
            url = test_data or "/"
            if "http" in url:
                return f"cy.visit('{url}');"
            return f"cy.visit(baseUrl + '{url}');"

        # Click
        if "click" in action_lower:
            return "cy.get('button').click();"

        # Fill
        if any(word in action_lower for word in ["enter", "fill", "type"]):
            value = test_data or "test"
            value_literal = json.dumps(value)
            if "email" in action_lower:
                return f"cy.get('input[type=\"email\"]').type({value_literal});"
            elif "password" in action_lower:
                return f"cy.get('input[type=\"password\"]').type({value_literal});"
            return f"cy.get('input').type({value_literal});"

        # Verify
        if any(word in action_lower for word in ["verify", "check", "assert"]):
            return "cy.get('body').should('be.visible');"

        return None