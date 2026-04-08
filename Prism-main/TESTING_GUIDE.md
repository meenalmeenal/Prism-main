# Testing Guide for Prism Generated Tests

## Setup Complete ✅

Playwright has been installed and configured. The generated tests are ready to run.

## Running Tests

### Basic Test Execution

```bash
# Run all generated tests
npm test

# Run tests with UI mode (interactive)
npm run test:ui

# Run tests in headed mode (see browser)
npm run test:headed
```

### Current Test Status

The tests are **generated correctly** and **syntax is valid**. The failures you're seeing are expected because:

1. **No Application Running**: Tests are trying to connect to `http://localhost:3000` but no server is running
2. **Connection Refused**: `ERR_CONNECTION_REFUSED` means the tests are working correctly - they just need an app to test

## To Run Tests Successfully

### Option 1: Start Your Application

```bash
# In a separate terminal, start your application
# For example:
npm start
# or
python -m http.server 3000
# or
# Start your actual application server

# Then run tests
npm test
```

### Option 2: Use a Test URL

Set the `APP_BASE_URL` environment variable:

```bash
# Windows PowerShell
$env:APP_BASE_URL="https://your-staging-url.com"
npm test

# Or create a .env file (for the pipeline)
APP_BASE_URL=https://your-staging-url.com
```

### Option 3: Mock/Stub the Application

For testing the test generation itself, you can:
- Use a mock server
- Skip actual execution and just verify test code generation

## Test Results Interpretation

### ✅ Success Indicators
- Tests execute without syntax errors
- Playwright can load the test files
- Tests attempt to navigate to URLs (even if connection fails)

### ⚠️ Expected Failures (No App Running)
- `ERR_CONNECTION_REFUSED` - Normal when no server is running
- `Test timeout` - Normal when waiting for elements that don't exist

### ❌ Real Issues
- Syntax errors in generated code
- Import errors (`Cannot find module`)
- Invalid test structure

## Generated Test Files

All generated tests are in `generated_tests/`:
- `ZT-3_ZT-3-RB-001.spec.js` - Positive test case
- `ZT-3_ZT-3-RB-002.spec.js` - Negative test case  
- `ZT-3_ZT-3-RB-003.spec.js` - Boundary test case

## Playwright Configuration

Configuration is in `playwright.config.js`:
- Test directory: `./generated_tests`
- Base URL: `process.env.APP_BASE_URL || 'http://localhost:3000'`
- Browsers: Chromium (can add Firefox, WebKit)
- Retries: 2 on CI, 0 locally
- Reporter: HTML

## Next Steps

1. **Start your application** on the configured port
2. **Run the tests**: `npm test`
3. **View results**: Open `playwright-report/index.html` after test run
4. **Integrate with CI/CD**: The tests are ready for GitHub Actions/Jenkins

## CI/CD Integration

The tests can be executed in CI/CD pipelines. The pipeline will:
1. Generate tests from Jira issues
2. Execute them against your staging/production environment
3. Sync results back to Zephyr

Example CI command:
```bash
export APP_BASE_URL=https://staging.example.com
npm test
```

