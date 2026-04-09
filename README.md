# 🏗️ Prism – AI-Powered Test Automation Framework

Prism is an **AI-driven test automation framework** that automatically generates, validates, and executes test cases from **Jira issues or GitHub pull requests**, and publishes them to **Zephyr test management** while generating **Playwright automation scripts**.

The framework combines **rule-based logic + LLM intelligence** to accelerate QA workflows and enable **end-to-end automated testing pipelines**.

This project is developed as part of the **Samsung PRISM R&D Program**.

---

# 🚀 Key Features

### 🤖 AI-Powered Test Generation

Generate test cases automatically using **Groq LLaMA models**.

### 🔗 Jira Integration

Automatically fetch requirements and user stories from Jira issues.

### 🧪 Zephyr Integration

Publish generated test cases to **Zephyr Scale** via REST API (Bearer token). If the API is unavailable or you enable **Zephyr Demo Mode**, cases are exported to `data/zephyr_demo/` with demo logs (`TC-101`, …) — **no JWT / ZAPI keys required** for demos.

### ⚙️ Automated Script Generation

Convert AI-generated test cases into **Playwright automation scripts**.

### 🧠 Hybrid Generation Engine

Supports both:

* Rule-based test generation
* AI-powered generation

### 🔐 PII Protection

Automatically detects and masks sensitive information.

### 📊 Execution Metrics

Tracks:

* Pass / Fail results
* Test coverage
* Generation statistics

### 🔁 Continuous Feedback Loop

Stores failed test results for improving future AI test generation.

---

# 🏗️ Architecture

Prism implements a **complete AI-driven QA pipeline**.

```
Jira Issue / GitHub PR
        ↓
Requirement Collector
        ↓
AI Test Generator (Groq LLaMA)
        ↓
Test Case Validator
        ↓
Zephyr Publisher
        ↓
Automation Code Generator
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
| Test Management | Zephyr                                 |
| CI Integration  | GitHub PRs                             |

---

# 🚀 Prerequisites

Install the following before setup:

* Node.js **v18+**
* Python **v3.9+**
* npm **v9+**
* Git
* Groq API account
* Jira Cloud account
* Zephyr Test Management installed in Jira

---

# ⚙️ Installation

## 1️⃣ Clone Repository

```bash
git clone https://github.com/your-org/Prism.git
cd Prism/Prism
```

---

## 2️⃣ Setup Python Environment

```bash
python -m venv .venv
```

Activate environment:

**Windows**

```bash
.venv\Scripts\activate
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

# 🔐 Environment Configuration

Create a `.env` file in the project root.

```
# -----------------------------
# Jira Configuration
# -----------------------------
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-jira-api-token

# -----------------------------
# Zephyr Configuration
# -----------------------------
ZEPHYR_BASE_URL=https://api.zephyrscale.smartbear.com/v2
ZEPHYR_API_TOKEN=your-zephyr-api-token
ZEPHYR_PROJECT_KEY=ZT

# -----------------------------
# Groq AI
# -----------------------------
GROQ_API_KEY=your-groq-api-key

# -----------------------------
# GitHub Integration
# -----------------------------
GITHUB_TOKEN=your-github-token

# -----------------------------
# Application Under Test
# -----------------------------
APP_BASE_URL=http://localhost:3000

# -----------------------------
# Pipeline Settings
# -----------------------------
ZEPHYR_DRY_RUN=false
MAX_AI_RETRIES=3
AI_RETRY_DELAY_SECONDS=2
```

---

# 🤖 Groq AI Setup

Prism uses **Groq LLM infrastructure** for generating intelligent test cases.

Create API key:

https://console.groq.com

Model used by default:

```
llama-3.3-70b-versatile
```

Alternative models:

| Model                   | Description     |
| ----------------------- | --------------- |
| llama-3.3-70b-versatile | Highest quality |
| llama-3.1-8b-instant    | Faster response |
| mixtral-8x7b-32768      | Large context   |

Modify model in:

```
src/ai_engine/ai_test_generator.py
```

---

# 🚀 Quick Start

## Generate Tests from Jira Issue

```
python -m src.pipeline.enhanced_pipeline jira ZT-123
```

---

## Generate Tests from GitHub Pull Request

```
python -m src.pipeline.enhanced_pipeline github_pr https://github.com/org/repo/pull/123
```

---

## Pipeline Options

```
--framework playwright
--dry-run
--max-retries 3
--retry-delay 2
```

---

# 🧪 Running Tests

Run all tests:

```
npm test
```

Run in UI mode:

```
npm run test:ui
```

Run with visible browser:

```
npm run test:headed
```

Run a specific generated test:

```
npx playwright test generated_tests/<test-file>.spec.js
```

---

# 📊 Test Reports

View Playwright report:

```
npx playwright show-report
```

---

# 📁 Project Structure

```
Prism
│
├── generated_tests
│
├── src
│   ├── ai_engine
│   ├── codegen
│   ├── collector
│   ├── executor
│   ├── feedback
│   ├── integrations
│   │   ├── jira_client.py
│   │   └── zephyr_client.py
│   │
│   ├── pipeline
│   └── validator
│
├── data
│   └── dashboard_data.json
│
├── mock-server.js
├── playwright.config.js
├── requirements.txt
└── package.json
```

---

# 📊 Metrics Output

Pipeline metrics are stored in:

```
data/dashboard_data.json
```

Example:

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

# 🔁 Test Generation Pipeline

Single Jira issue:

```
python -m src.pipeline.enhanced_pipeline jira ZT-123
```

Batch issues:

```
python -m src.pipeline.enhanced_pipeline jira ZT-123,ZT-124
```

GitHub PR:

```
python -m src.pipeline.enhanced_pipeline github_pr <PR_URL>
```

---

# 🧪 Mock Application

A local **mock login application** is provided for testing.

Server runs automatically when executing tests.

Port:

```
3000
```

Endpoints:

| Endpoint           | Description           |
| ------------------ | --------------------- |
| GET /              | Login UI              |
| POST /api/login    | Authentication        |
| GET /api/protected | JWT protected route   |
| GET /boundary-test | Boundary testing page |

---

# 🐛 Troubleshooting

## Groq API Error

Verify `GROQ_API_KEY`.

## Playwright Browser Missing

```
npx playwright install
```

## Zephyr integration

Prism integrates with **Zephyr Scale (SmartBear) Cloud** using a **Bearer API token** (`ZEPHYR_API_TOKEN`).  
You do **not** need Zephyr ZAPI JWT `accessKey` / `secretKey` for this client.

### Behaviour

| Condition | What happens |
|-----------|----------------|
| `ZEPHYR_API_TOKEN` set, `ZEPHYR_DRY_RUN` / `ZEPHYR_DEMO_MODE` off | Pipeline calls the real **Zephyr Scale REST API** (`/v2/testcases`, cycles, executions). |
| No token, `ZEPHYR_DRY_RUN=true`, or `ZEPHYR_DEMO_MODE=true` | **Zephyr Demo Mode**: no external API calls; structured JSON export + demo logs (`TC-101`, `TC-102`, …). |
| Live API error (401, 404, network, etc.) | Automatic fallback to **Zephyr Demo Mode** — the pipeline **does not fail**. |

### Environment variables

```env
ZEPHYR_API_TOKEN=your-zephyr-scale-api-token
ZEPHYR_PROJECT_KEY=ZT
ZEPHYR_BASE_URL=https://api.zephyrscale.smartbear.com/v2   # optional override
ZEPHYR_DRY_RUN=true          # force demo-style behaviour (no live calls)
ZEPHYR_DEMO_MODE=true        # always use Demo Mode (for Samsung PRISM demos)
JIRA_BASE_URL=https://your-domain.atlassian.net            # used in UI hints
```

### Demo Mode output

- Console logs such as: `Publishing test case to Zephyr...`, `Test Case TC-101 created in Zephyr (Demo Mode)`.
- Export file: `data/zephyr_demo/<ISSUE-KEY>_zephyr_published.json` (traceable list of cases linked to the Jira key).
- Hint to open the issue in Jira and use **Zephyr / Zephyr Scale** in the UI to correlate tests.

### Code entry point

`ZephyrClient.publish_test_cases(issue_key, test_cases)` — synchronous, safe from any caller; used by `pipeline_runner` and the enhanced pipeline.

## Port 3000 Already Used

```
netstat -ano | findstr :3000
taskkill /PID <PID> /F
```

---

# 🔍 Debug Mode

Enable debug logs:

```
LOG_LEVEL=DEBUG
```

Run pipeline:

```
python -m src.pipeline.enhanced_pipeline jira ZT-123
```

---

# 📜 License

MIT License
