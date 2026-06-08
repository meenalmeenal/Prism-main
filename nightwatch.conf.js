module.exports = {
  src_folders: ['generated_tests'],
  webdriver: {
    start_process: true
  },
  test_settings: {
    default: {
      launch_url: 'http://localhost:3000',
      desiredCapabilities: {
        browserName: 'chrome',
        'goog:chromeOptions': {
          args: [
            '--no-sandbox',
            '--disable-gpu',
            '--ignore-certificate-errors'
          ]
        }
      }
    }
  }
};
