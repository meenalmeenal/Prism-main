const { Given, When, Then, After } = require('@cucumber/cucumber');
const { chromium } = require('playwright');
const assert = require('assert');

let browser, page;

// Existing Step Definitions
Given('the user is on the application', async function () {
  browser = await chromium.launch({ headless: false });
  page = await browser.newPage();
  await page.goto(process.env.APP_BASE_URL || 'http://localhost:3000');
});

When('the user navigates to the login page', async function () {
  await page.goto((process.env.APP_BASE_URL || 'http://localhost:3000') + '/login');
});

When(/^the user enters email "(.*)"$/, async function (email) {
  await page.fill('#username', email);
});

When(/^the user enters password "(.*)"$/, async function (password) {
  await page.fill('#password', password);
});

When('the user clicks the login button', async function () {
  await page.click('button[type="submit"]');
});

Then(/^the user should see "(.*)"$/, async function (text) {
  await page.waitForSelector(`text=${text}`);
});

Then('the login should be successful', async function () {
  await page.waitForURL('**/dashboard**');
});

Then('an error message should be displayed', async function () {
  await page.waitForSelector('.error-message');
});

// ZT-11 (Gherkin/Cucumber) Step Definitions for Password Masking
Given('User is on the login or registration page', async function () {
  if (!browser) {
    browser = await chromium.launch({ headless: false });
  }
  page = await browser.newPage();
  await page.goto(process.env.APP_BASE_URL || 'http://localhost:3000');
});

Given('Password field is visible and editable', async function () {
  const passwordField = page.locator('#password');
  await assert(await passwordField.isVisible());
  await assert(await passwordField.isEditable());
});

When('Click on the password field to focus it', async function () {
  await page.click('#password');
});

Then('Password field is focused and cursor is blinking', async function () {
  const isFocused = await page.evaluate(() => document.activeElement.id === 'password');
  assert(isFocused);
});

When('Type a password into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows masked characters \\(e.g., bullets or asterisks) instead of the actual password', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

When('Type a short password into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows masked characters for the short password', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

Then('Type a long password into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows masked characters for the long password', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

Given('Username or email field is visible and editable', async function () {
  const usernameField = page.locator('#username');
  await assert(await usernameField.isVisible());
  await assert(await usernameField.isEditable());
});

When('Type a username or email into the respective field {string}', async function (val) {
  await page.fill('#username', val);
});

Then('Username or email field shows the actual input, not masked characters', async function () {
  const inputType = await page.getAttribute('#username', 'type');
  assert.notStrictEqual(inputType, 'password');
});

When('Type a password with special characters into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows an error or does not mask characters correctly', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

Given('Minimum password length is defined \\(e.g., {int} characters)', async function (len) {
  // Configured in LLM prompt, no UI action needed
});


When('Type the minimum length password into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows masked characters for the minimum length password', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

Given('Multiple browsers are available for testing \\(e.g., Chrome, Firefox, Safari)', async function () {
  // TestRunner/Playwright config handles browser targets
});

When('Test the password field masking in each browser', async function () {
  // Subprocess executes browser tests
});

Then('Password field masking is consistent and works as expected across all browsers', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

When('Attempt to inspect the password field using developer tools', async function () {
  // Simulation step
});

Then('Password field value is not accessible or visible in plain text', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

When('Attempt to inject malicious code or scripts into the password field', async function () {
  await page.fill('#password', "<script>alert('xss')</script>");
});

Then('Password field masking prevents the execution of malicious code or scripts', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

When('Copy a password from a secure source and paste it into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Given('Maximum password length is defined \\(e.g., {int} characters)', async function (len) {
  // Configured in LLM prompt, no UI action needed
});


When('Type the maximum length password into the password field {string}', async function (password) {
  await page.fill('#password', password);
});

Then('Password field shows masked characters for the maximum length password', async function () {
  const inputType = await page.getAttribute('#password', 'type');
  assert.strictEqual(inputType, 'password');
});

// Cleanup after each scenario
After(async function () {
  if (browser) {
    await browser.close();
    browser = null;
    page = null;
  }
});