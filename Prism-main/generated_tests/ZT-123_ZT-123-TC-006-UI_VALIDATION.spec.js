import { test, expect } from '@playwright/test';

// Auto-generated test case for ZT-123
// Test ID: ZT-123-TC-006-UI_VALIDATION
// Type: ui_validation, Priority: P2

const baseUrl = process.env.APP_BASE_URL || 'http://localhost:3000';

test.describe('ZT-123: Login page field validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(baseUrl);
    // Precondition: User is on the login page
  });

  test('Login page field validation', async ({ page }) => {
    // Step 1: Navigate to the login page
    // Expected: Login page loads successfully with email and password fields visible
    await page.goto(baseUrl);
    // Step 2: Leave email field empty and click the login button
    // Expected: Error message is displayed indicating email field is required
    await page.click('button');
    // Step 3: Enter valid email address in the email field and leave password field empty
    // Expected: Error message is displayed indicating password field is required
    await page.fill('#username', 'testuser@example.com');
  });
});