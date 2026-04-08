import { test, expect } from '@playwright/test';

// Auto-generated test case for ZT-20
// Test ID: ZT-20-TC-006-UI_VALIDATION
// Type: ui_validation, Priority: P2

const baseUrl = process.env.APP_BASE_URL || 'http://localhost:3000';

test.describe('ZT-20: Login form validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(baseUrl);
    // Precondition: User is on the login page
  });

  test('Login form validation', async ({ page }) => {
    // Step 1: Navigate to the login page
    // Expected: Login page loads successfully with email and password fields visible
    await page.goto(baseUrl);
    // Step 2: Leave the email field blank
    // Expected: An error message is displayed indicating that the email field is required
    // Step 3: Leave the password field blank
    // Expected: An error message is displayed indicating that the password field is required
    // Step 4: Enter an invalid email address in the email field
    // Expected: An error message is displayed indicating that the email address is not valid
    await page.fill('#username', 'invalidemail');
  });
});