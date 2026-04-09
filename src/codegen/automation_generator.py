"""Automation code generator for test cases.

Converts validated test cases into executable automation scripts
for Nightwatch.js, Playwright, and Cypress frameworks.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class AutomationGenerator:
    """Generates automation test scripts from validated test cases."""

    SUPPORTED_FRAMEWORKS = ["nightwatch", "playwright", "cypress"]

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
                if self.framework == "playwright":
                    code = self._generate_playwright(test_case, issue_key, base_url)
                elif self.framework == "nightwatch":
                    code = self._generate_nightwatch(test_case, issue_key, base_url)
                else:  # cypress
                    code = self._generate_cypress(test_case, issue_key, base_url)

                # Save to file
                test_id = test_case.get("id", "unknown").replace(" ", "_").replace("/", "_")
                filename = f"{issue_key}_{test_id}.spec.js"
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
            f"test.describe('{issue_key}: {title[:60]}', () => {{",
        ]

        # Add preconditions as setup
        lines.append("  test.beforeEach(async ({ page }) => {")
        lines.append("    await page.goto(baseUrl);")
        if preconditions:
            for precond in preconditions:
                lines.append(f"    // Precondition: {precond}")
        lines.append("  });")
        lines.append("")

        # Generate test steps
        test_name = title.replace('"', "'")[:80]
        lines.append(f"  test('{test_name}', async ({{ page }}) => {{")

        for step in steps:
            step_num = step.get("step_number", 0)
            action = step.get("action", "")
            test_data = step.get("test_data")
            expected = step.get("expected_result", "")

            lines.append(f"    // Step {step_num}: {action}")
            if expected:
                lines.append(f"    // Expected: {expected}")

            # Convert action to Playwright code
            playwright_code = self._action_to_playwright(action, test_data, expected)
            if playwright_code:
                lines.append(f"    {playwright_code}")

        lines.append("  });")
        lines.append("});")

        return "\n".join(lines)

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
            f"describe('{issue_key}: {title[:60]}', () => {{",
        ]

        # Add preconditions as before hook
        if preconditions:
            lines.append("  beforeEach(() => {")
            for precond in preconditions:
                lines.append(f"    // Precondition: {precond}")
            lines.append("  });")
            lines.append("")

        # Generate test
        test_name = title.replace('"', "'")[:80]
        lines.append(f"  it('{test_name}', () => {{")

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

    def _action_to_playwright(self, action: str, test_data: Optional[str], expected: str) -> Optional[str]:
        """Convert action text to Playwright code."""
        action_lower = action.lower()

        # Navigation
        if "navigate" in action_lower or "open" in action_lower or "go to" in action_lower:
            return f"await page.goto(baseUrl);"

        # Click
        if "click" in action_lower:
            if "button" in action_lower:
                return "await page.click('button');"
            return "await page.click('a');"

        # Fill/Enter
        if any(word in action_lower for word in ["enter", "fill", "type", "input"]):
            if "email" in action_lower or "username" in action_lower:
                value = test_data or "testuser"
                return f"await page.fill('#username', '{value}');"
            elif "password" in action_lower:
                value = test_data or "password"
                return f"await page.fill('#password', '{value}');"
            else:
                value = test_data or "test value"
                return f"await page.fill('input[type=\"text\"]', '{value}');"

        # Verify/Assert
        if any(word in action_lower for word in ["verify", "check", "assert", "expect"]):
            if "visible" in action_lower or "display" in action_lower:
                return "await expect(page.locator('body')).toBeVisible();"
            return "// TODO: Add specific assertion"

        # Wait
        if "wait" in action_lower:
            return "await page.waitForTimeout(1000);"

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
            return f"browser.setValue('input', '{value}');"

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
            if "email" in action_lower:
                return f"cy.get('input[type=\"email\"]').type('{value}');"
            elif "password" in action_lower:
                return f"cy.get('input[type=\"password\"]').type('{value}');"
            return f"cy.get('input').type('{value}');"

        # Verify
        if any(word in action_lower for word in ["verify", "check", "assert"]):
            return "cy.get('body').should('be.visible');"

        return None

