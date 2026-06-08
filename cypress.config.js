const { defineConfig } = require("cypress");

module.exports = defineConfig({
  e2e: {
    baseUrl: 'http://localhost:3000',
    supportFile: false,
    specPattern: 'generated_tests/**/*.spec.js',
    video: false,
    screenshotOnRunFailure: false,
  },
});
