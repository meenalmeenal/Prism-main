module.exports = {
  default: {
    paths: ['generated_tests/**/*.feature'],
    require: ['steps/**/*.js'],
    format: ['progress', 'json:test-results/cucumber-report.json'],
    publishQuiet: true,
  }
};