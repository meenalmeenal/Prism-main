import { test, expect } from '@playwright/test';

// Auto-generated test case for ZT-123
// Test ID: ZT-123-TC-002-POSITIVE
// Type: positive, Priority: P2

const baseUrl = process.env.APP_BASE_URL || 'http://localhost:3000';

test.describe('ZT-123: User logs in with valid credentials and special characters i', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(baseUrl);
    // Precondition: User is on the login page
    // Precondition: User has a valid registered account with special characters in password
    // Precondition: Browser cookies are enabled
  });

  test('User logs in with valid credentials and special characters in password', async ({ page }) => {
    // Step 1: Navigate to the login page
    // Expected: Login page loads successfully with email and password fields visible
    await page.goto(baseUrl);
    // Step 2: Enter valid email address in the email field
    // Expected: Email field is populated with the entered email
    await page.fill('#username', 'testuser2@example.com');
    // Step 3: Enter valid password with special characters in the password field
    // Expected: Password field shows masked characters, login button becomes enabled
    await page.fill('#password', 'P@ssw0rd!');
    // Step 4: Click the login button
    // Expected: User is redirected to dashboard page, welcome message displays with user's name
    await page.click('button');
    // Step 5: Verify user session is established
    // Expected: User profile icon is visible in header, logout option is available
    // TODO: Add specific assertion
  });
});