const config = {
  testDir: './generated_tests',
  reporter: 'html',
  timeout: 30 * 1000,
  retries: process.env.CI ? 2 : 1,
  expect: {
    timeout: 5000
  },
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    viewport: { width: 1280, height: 720 },
    ignoreHTTPSErrors: true,
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'node mock-server.js',
    url: 'http://localhost:3000',
    reuseExistingServer: false,
    timeout: 10000,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
};

module.exports = config;