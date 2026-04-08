const axios = require('axios');

// This is your Zephyr logic and Test data combined into one file to avoid "Module Not Found"
async function runSingleFileTest() {
  const url = 'https://api.zephyrscale.smartbear.com/v2/testcases';
  const token = process.env.ZEPHYR_API_TOKEN;

  console.log("🚀 Starting Connection Test...");

  const payload = {
    projectKey: "ZT", // Ensure this is your Jira Project Key
    name: "GitHub Automation Test Case",
    statusName: "Draft",
    priorityName: "Normal",
    testScript: {
      type: "STEP_BY_STEP",
      steps: [
        {
          description: "Open the application",
          expectedResult: "Application is open"
        },
        {
          description: "Verify login",
          expectedResult: "Login successful"
        }
      ]
    }
  };

  try {
    const response = await axios.post(url, payload, {
      headers: {
        'Authorization': `Bearer ${token?.trim()}`,
        'Content-Type': 'application/json'
      }
    });
    console.log(`✅ SUCCESS! Created Zephyr Test Case: ${response.data.key}`);
  } catch (error) {
    console.error("❌ FAILED!");
    if (error.response) {
      console.error("Status:", error.response.status);
      console.error("Data:", JSON.stringify(error.response.data, null, 2));
    } else {
      console.error("Message:", error.message);
    }
  }
}

runSingleFileTest();
