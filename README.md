#  Prism – AI-Powered Test Automation Framework

Prism is an **AI-driven test automation framework** that automatically generates, validates, and executes test cases from **Jira issues or GitHub pull requests**, and publishes them to **Zephyr test management** while generating **Playwright automation scripts**.

The framework combines **rule-based logic + LLM intelligence** to accelerate QA workflows and enable **end-to-end automated testing pipelines**.

This project is developed as part of the **Samsung PRISM R&D Program**.

---

#  Key Features

###  AI-Powered Test Generation
Generate test cases automatically using **Groq LLaMA models**.

###  GitHub PR Integration
Automatically extract Jira issue keys from GitHub Pull Requests and trigger the full test pipeline.

###  Jira Integration
Automatically fetch requirements and user stories from Jira issues.

###  Zephyr Integration
Publish generated test cases to **Zephyr Scale** via REST API (Bearer token). If the API is unavailable or you enable **Zephyr Demo Mode**, cases are exported to `data/zephyr_demo/` with demo logs — **no JWT / ZAPI keys required** for demos.

###  Automated Script Generation
Convert AI-generated test cases into **Playwright automation scripts**.

###  Hybrid Generation Engine
Supports both rule-based and AI-powered test generation with automatic fallback.

###  PII Protection
Automatically detects and masks sensitive information.

###  Execution Metrics
Tracks pass/fail results, test coverage, and generation statistics.

###  Continuous Feedback Loop
Stores failed test results for improving future AI test generation.

---

#  Architecture

```
Jira Issue / GitHub PR
        ↓
Requirement Collector (PR Collector / Jira Client)
        ↓
AI Test Generator (Groq LLaMA)
        ↓
Test Case Validator
        ↓
Zephyr Publisher
        ↓
Automation Code Generator (Playwright .spec.js)
        ↓
Playwright Test Execution
        ↓
Metrics & Feedback Loop
```

---

# 🛠 Tech Stack

| Component       | Technology                             |
| --------------- | -------------------------------------- |
| Backend         | Python 3.9+                            |
| AI Engine       | Groq LLaMA (`llama-3.3-70b-versatile`) |
| Automation      | Playwright                             |
| Package Manager | npm / Node.js                          |
| Issue Tracking  | Jira Cloud                             |
| Test Management | Zephyr Scale (SmartBear)               |
| CI Integration  | GitHub PRs (`PyGithub`)                |

---

#  Prerequisites

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

#  Installation

## 1️⃣ Clone Repository

```bash
git clone https://github.com/meenalmeenal/Prism.git
cd Prism
```

---

## 2️⃣ Setup Python Environment

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

---

## 3️⃣ Install Node Dependencies

```bash
npm install
```

Install Playwright browsers:

```bash
npx playwright install
```

---

#  Environment Configuration

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
ZEPHYR_PUBLISH_ENABLED=true
ZEPHYR_DRY_RUN=false

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

#  Quick Start

## Generate Tests from a Jira Issue

```bash
python -m src.pipeline.enhanced_pipeline jira ZT-123
```

## Generate Tests from a GitHub Pull Request

```bash
python -m src.pipeline.enhanced_pipeline github_pr https://github.com/org/repo/pull/1
```

## With Options

```bash
python -m src.pipeline.enhanced_pipeline github_pr <PR_URL> --framework playwright --dry-run --max-retries 3
```

| Flag | Default | Description |
|------|---------|-------------|
| `--framework` | `playwright` | Automation framework for script generation |
| `--dry-run` | `false` | Skip publishing to Zephyr |
| `--max-retries` | `3` | AI generation retry attempts |
| `--retry-delay` | `2.0` | Seconds between retries |

---

#  Running Tests

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

#  Project Structure

```
Prism/
│
├── src/
│   ├── ai_engine/            # Groq LLM + rule-based test generator
│   ├── codegen/              # Playwright .spec.js script generator
│   ├── collector/            # PR & Jira requirement collectors
│   ├── dashboard/            # Metrics tracker
│   ├── executor/             # Playwright test executor
│   ├── feedback/             # Feedback loop for failed tests
│   ├── integrations/
│   │   ├── github_client.py  # GitHub API (PyGithub + Auth.Token)
│   │   ├── jira_client.py    # Jira REST API client
│   │   └── zephyr_client.py  # Zephyr Scale REST API client
│   ├── pipeline/
│   │   ├── enhanced_pipeline.py  # Main CLI entry point
│   │   └── pipeline_runner.py    # Core pipeline orchestration
│   └── validator/            # Test case validator
│
├── data/                     # Runtime output (gitignored)
│   └── dashboard_data.json
│
├── generated_tests/          # Generated Playwright specs (gitignored)
├── mock-server.js            # Local mock app (port 3000)
├── playwright.config.js      # Playwright configuration
├── requirements.txt          # Python dependencies
├── package.json              # Node dependencies
├── .env.example              # Environment variable template
└── README.md
```

---

#  Metrics Output

Pipeline metrics are written to `data/dashboard_data.json`:

```json
{
  "total_test_cases": 5,
  "generation_time_seconds": 10.2,
  "validation_passed": 5,
  "validation_failed": 0,
  "execution_passed": 4,
  "execution_failed": 1,
  "generation_mode": "ai_groq"
}
```

---

#  Mock Application

A local **mock login application** is bundled for testing without a real app.

| Endpoint           | Description           |
| ------------------ | --------------------- |
| `GET /`            | Login UI              |
| `POST /api/login`  | Authentication        |
| `GET /api/protected` | JWT protected route |
| `GET /boundary-test` | Boundary testing    |

Port: `3000` (started automatically during test runs)

---

#  Zephyr Integration Details

Prism integrates with **Zephyr Scale (SmartBear) Cloud** using a **Bearer API token** — no ZAPI JWT `accessKey`/`secretKey` required.

| Condition | Behaviour |
|-----------|-----------|
| Token set, dry-run off | Calls live **Zephyr Scale REST API** (`/v2/testcases`, cycles, executions) |
| No token, `ZEPHYR_DRY_RUN=true` | **Demo Mode**: JSON export to `data/zephyr_demo/`, no external calls |
| Live API error | Auto-fallback to Demo Mode — pipeline never fails |

---

#  Troubleshooting

### GitHub 401 Bad Credentials
- Generate a fresh **classic PAT** at [github.com/settings/tokens](https://github.com/settings/tokens) with the `repo` scope
- Paste it into `.env` as `GITHUB_TOKEN=ghp_...` (no quotes)
- The client uses `Auth.Token()` (PyGithub ≥ 2.x) — the old positional `Github(token)` API is deprecated

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

#  License

MIT License
