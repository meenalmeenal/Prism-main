# Prism – AI-Powered Test Automation Framework

Prism is an **AI-driven test automation framework** that automatically generates, validates, and executes test cases from **Jira issues, GitHub pull requests, or OpenAPI/Swagger specifications**, and publishes them directly to **Zephyr Scale** while generating **Playwright automation scripts**.

The framework combines **rule-based logic + LLM intelligence** to accelerate QA workflows and enable **end-to-end automated testing pipelines**.

This project is developed as part of the **Samsung PRISM R&D Program**.

---

# 🚀 Key Features

### 🔌 OpenAPI / Swagger Spec Integration
Directly parse OpenAPI/Swagger JSON or YAML files (or URLs) to extract paths, methods, response codes, and parameters to generate structured API acceptance criteria and corresponding test cases.

### 🧠 AI-Powered Test Generation
Generate comprehensive test cases automatically using **Groq LLaMA models** (`llama-3.3-70b-versatile`).

### 🐙 GitHub PR Integration
Automatically extract Jira issue keys from GitHub Pull Requests and trigger the full test pipeline.

### 🎫 Jira Integration
Automatically fetch requirements and user stories from Jira issues.

### 📊 Zephyr Scale Publishing
Publish generated test cases and test execution results directly to **Zephyr Scale** via REST API (Bearer token).

### 📝 Automated Script Generation
Convert AI-generated test cases into **Playwright, Cypress, or Nightwatch.js** automation scripts.

### 🛡️ PII Protection
Automatically detect and mask sensitive information before sending prompts to the LLM.

### 📈 Execution Metrics
Track pass/fail results, test coverage, and generation statistics to generate local dashboards.

### 🔁 Continuous Feedback Loop
Log failed test results in a feedback store to continuously refine and improve future AI test generations.

---

# 📐 Architecture

```
Jira Issue / GitHub PR / OpenAPI Spec
                 ↓
Requirement Collector (PR / Jira / Spec)
                 ↓
 AI Test Generator (Groq LLaMA / Fallback)
                 ↓
        Test Case Validator
                 ↓
         Zephyr Publisher
                 ↓
  Automation Code Generator (.spec.js)
                 ↓
       Test Suite Execution
                 ↓
     Metrics & Feedback Loop
```

---

# 🛠️ Tech Stack

| Component       | Technology                             |
| --------------- | -------------------------------------- |
| Backend         | Python 3.9+                            |
| AI Engine       | Groq LLaMA (`llama-3.3-70b-versatile`) |
| Automation      | Playwright, Cypress, Nightwatch.js     |
| Package Manager | npm / Node.js                          |
| Issue Tracking  | Jira Cloud                             |
| Test Management | Zephyr Scale (SmartBear)               |
| CI Integration  | GitHub PRs (`PyGithub`)                |

---

# 📋 Prerequisites

Install the following before setup:

* Node.js **v18+**
* Python **v3.9+**
* npm **v9+**
* Git
* Groq API account → [console.groq.com](https://console.groq.com)
* Jira Cloud account
* Zephyr Scale installed in Jira
* GitHub Personal Access Token (classic, `repo` scope)

---

# ⚙️ Installation

### 1️⃣ Clone Repository

```bash
git clone https://github.com/meenalmeenal/Prism_main.git
cd Prism_main
```

### 2️⃣ Setup Python Environment

```bash
python -m venv .venv
```

Activate (Windows):

```bash
.venv\Scripts\activate
```

Activate (macOS/Linux):

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 3️⃣ Install Node Dependencies

```bash
npm install
```

Install Playwright browsers:

```bash
npx playwright install
```

---

# 🔧 Environment Configuration

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

```env
# ──────────────────────────────────────────────
# Jira
# ──────────────────────────────────────────────
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token

# ──────────────────────────────────────────────
# Zephyr Scale
# ──────────────────────────────────────────────
ZEPHYR_BASE_URL=https://prod-api.zephyr4jiracloud.com/v2/
ZEPHYR_API_TOKEN=your-zephyr-api-token
ZEPHYR_PROJECT_KEY=ZT
ZEPHYR_TEST_CYCLE_KEY=ZT-R1

# ──────────────────────────────────────────────
# Groq AI
# ──────────────────────────────────────────────
AI_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key

# ──────────────────────────────────────────────
# GitHub Integration
# ──────────────────────────────────────────────
GITHUB_TOKEN=your-github-personal-access-token

# ──────────────────────────────────────────────
# Pipeline Settings
# ──────────────────────────────────────────────
MAX_AI_RETRIES=3
AI_RETRY_DELAY_SECONDS=2.0
AI_FALLBACK_ENABLED=true
```

> **GitHub Token**: Generate at GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic). Select the **`repo`** scope.

---

# 🏁 Quick Start

Running the enhanced pipeline uses the following general structure:
```bash
python -m src.pipeline.enhanced_pipeline <source> <identifier> [options]
```

### 1. Generate Tests from a Jira Issue

```bash
python -m src.pipeline.enhanced_pipeline jira ZT-123
```

### 2. Generate Tests from a GitHub Pull Request

```bash
python -m src.pipeline.enhanced_pipeline github_pr https://github.com/org/repo/pull/1
```

### 3. Generate Tests from an OpenAPI / Swagger Spec
You can pass a local YAML/JSON spec file or a direct URL to the specification:

```bash
# Using a local spec file
python -m src.pipeline.enhanced_pipeline api_spec data/test_spec.yaml

# Using a remote spec URL
python -m src.pipeline.enhanced_pipeline api_spec https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/examples/v3.0/petstore.yaml
```

---

### CLI Command Options

| Flag | Default | Description |
|------|---------|-------------|
| `--framework` | `playwright` | Automation framework (`playwright`, `nightwatch`, or `cypress`) |
| `--max-retries` | `3` | AI generation retry attempts |
| `--retry-delay` | `2.0` | Seconds between retries |
| `--team` | `None` | Optional team name tag |

---

# 🧪 Running Tests

```bash
npm test                  # Run all Playwright tests
npm run test:ui           # Open Playwright UI mode
npm run test:headed       # Run with visible browser
npx playwright show-report  # View HTML report
```

Run a specific generated test:

```bash
npx playwright test generated_tests/<test-file>.spec.js
```

---

# 📂 Project Structure

```
Prism/
│
├── src/
│   ├── ai_engine/            # Groq LLM + rule-based test generators
│   ├── codegen/              # Playwright, Cypress, & Nightwatch generator
│   ├── collector/            # PR, Jira, & OpenAPI requirement collectors
│   ├── dashboard/            # Metrics tracker
│   ├── executor/             # Automation test executors
│   ├── feedback/             # Feedback loop for failed tests
│   ├── integrations/
│   │   ├── github_client.py  # GitHub API client
│   │   ├── jira_client.py    # Jira REST API client
│   │   └── zephyr_client.py  # Zephyr Scale REST API client
│   ├── pipeline/
│   │   ├── enhanced_pipeline.py  # Main CLI entry point
│   │   └── pipeline_runner.py    # Core pipeline orchestration
│   └── validator/            # Schema validation and deduplication
│
├── data/                     # Metrics, feedback logs, and temp specs
│   └── dashboard_data.json
│
├── generated_tests/          # Generated Playwright/Cypress/Nightwatch specs
├── mock-server.js            # Local mock app (port 3000)
├── playwright.config.js      # Playwright configuration
├── requirements.txt          # Python dependencies
├── package.json              # Node dependencies
├── .env.example              # Environment variable template
└── README.md
```

---

# 📊 Metrics Dashboard

Pipeline metrics are written to `data/dashboard_data.json` and can be viewed locally or fed into the dashboard view:

```json
{
  "coverage": {
    "period_days": 30,
    "total_issues_processed": 5,
    "total_tests_generated": 15,
    "total_tests_executed": 12,
    "total_passed": 10,
    "total_failed": 2,
    "overall_pass_rate": 83.33
  },
  "flaky_tests": [],
  "test_type_distribution": {
    "positive": 8,
    "negative": 5,
    "boundary": 2
  },
  "priority_distribution": {
    "High": 6,
    "Medium": 7,
    "Low": 2
  }
}
```

---

# 🖥️ Mock Application

A local **mock login application** is bundled for testing the generated scripts.

| Endpoint           | Description           |
| ------------------ | --------------------- |
| `GET /`            | Login UI              |
| `POST /api/login`  | Authentication        |
| `GET /api/protected` | JWT protected route |
| `GET /boundary-test` | Boundary testing    |

Port: `3000` (started automatically during automated test runs).

---

# 🔍 Troubleshooting

### GitHub 401 Bad Credentials
* Generate a fresh **classic PAT** at [github.com/settings/tokens](https://github.com/settings/tokens) with the `repo` scope.
* Paste it into `.env` as `GITHUB_TOKEN=ghp_...` (no quotes).

### Groq API Error
Verify `GROQ_API_KEY` at [console.groq.com](https://console.groq.com).

### Playwright Browser Missing
```bash
npx playwright install
```

### Port 3000 Already in Use
```bash
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

### Debug Logging
```bash
LOG_LEVEL=DEBUG python -m src.pipeline.enhanced_pipeline jira ZT-123
```

---

# 📄 License

MIT License
