# Prism: How We Solve It Now — Complete Architecture & Pipeline

> **Project:** Prism — AI-Powered Test Automation Framework
> **Stack:** Python 3.13 · Groq LLaMA (llama-3.3-70b-versatile) · Playwright · aiohttp · Jira Cloud · Zephyr Scale
> **Samsung PRISM @ IIIT Naya Raipur**
> This document covers the complete current architecture: every subsystem, technique, and design decision — from webhook event to Zephyr test cycle.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Three Input Sources](#2-the-three-input-sources)
3. [Webhook Listener — Auto-Trigger Pipeline](#3-webhook-listener--auto-trigger-pipeline)
4. [GitHub PR Path — Auto-Create Jira Story](#4-github-pr-path--auto-create-jira-story)
5. [AI Engine — Groq LLaMA Test Generation](#5-ai-engine--groq-llama-test-generation)
6. [Test Validator](#6-test-validator)
7. [Zephyr Scale Publisher](#7-zephyr-scale-publisher)
8. [Automation Generator — Playwright Script Generation](#8-automation-generator--playwright-script-generation)
9. [Test Executor](#9-test-executor)
10. [Feedback Loop & Metrics Dashboard](#10-feedback-loop--metrics-dashboard)
11. [PII Protection Layer](#11-pii-protection-layer)
12. [Backend CLI & API Architecture](#12-backend-cli--api-architecture)
13. [Complete Pipeline Flow](#13-complete-pipeline-flow)
14. [Performance Metrics](#14-performance-metrics)

---

## 1. System Overview

Prism converts requirements (Jira stories, GitHub PRs, or OpenAPI specs) into fully executed Playwright test suites through a multi-stage intelligent pipeline:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INPUT SOURCES                                   │
│                                                                         │
│  [Jira Story] ─────────────────────────────────────────────────────────►│
│  (via webhook or CLI — ZT-23 → fetch story + ACs)                       │
│                                                                         │
│  [GitHub PR] ──────────────────────────────────────────────────────────►│
│  (via webhook or CLI — auto-creates Jira story if no key in title)      │
│                                                                         │
│  [OpenAPI / Swagger Spec] ─────────────────────────────────────────────►│
│  (YAML/JSON file or URL — extracts paths, methods, responses)           │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               ENHANCED PIPELINE (enhanced_pipeline.py)                   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   pipeline_runner.py                              │  │
│  │                                                                  │  │
│  │  1. Fetch Requirements   → NormalizedIssue                       │  │
│  │  2. AI Test Generation   → TestCase[]  (Groq LLaMA)             │  │
│  │  3. Validation           → Deduplicated, schema-valid cases      │  │
│  │  4. Zephyr Publish       → Test cases + executions in Zephyr    │  │
│  │  5. Automation Codegen   → .spec.js files (Playwright)           │  │
│  │  6. Test Execution       → Playwright runs with JSON reporter    │  │
│  │  7. Result Upload        → Pass/fail per test in Zephyr         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────────────────┐  │
│  │ jira_client   │  │ zephyr_client │  │ dashboard_data.json        │  │
│  │ (fetch + create│  │ (cycles, cases│  │ (metrics, pass rates,      │  │
│  │  + sprint add) │  │  executions)  │  │  test type distribution)   │  │
│  └───────────────┘  └───────────────┘  └────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        GENERATED OUTPUT                                  │
│                                                                         │
│  generated_tests/                                                       │
│  ├── ZT-3_ZT-3-TC-001-POSITIVE.spec.js                                 │
│  ├── ZT-3_ZT-3-TC-002-POSITIVE.spec.js                                 │
│  ├── ZT-3_ZT-3-TC-003-NEGATIVE.spec.js                                 │
│  └── ...                                                                │
│                                                                         │
│  data/dashboard_data.json    ← Metrics for all pipeline runs            │
│  logs/webhook_listener.log   ← Webhook event log                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. The Three Input Sources

### Source A: Jira Issue (Primary)

The Jira path is the foundational input. When a Jira story key is provided (e.g. `ZT-3`), Prism fetches the full story from the Jira REST API and normalizes it:

```
Jira Issue Key (e.g. ZT-3)
  → jira_client.fetch_issue(key)
  → jira_client._normalize_issue(payload)    # → NormalizedIssue
  → Extract: summary, description, ACs from description text
  → pipeline_runner.run_pipeline(issue)
```

The Jira REST API endpoint used is `/rest/api/3/issue/{key}`. Authentication is via HTTP Basic Auth (email + API token). The response is a rich JSON document containing the issue's summary, description (in Atlassian Document Format), and any linked acceptance criteria.

**Key advantage:** Jira is the source of truth for requirements in most enterprises. Starting from a Jira story means the generated tests are directly traceable back to the business requirement.

### Selection Logic (in `src/pipeline/enhanced_pipeline.py`)

```python
async def _resolve_issue_key(source: str, identifier: str) -> str:
    if source == "jira":
        # identifier IS the key (e.g. "ZT-3")
        return identifier

    elif source == "github_pr":
        # Check PR title for embedded Jira key
        pr_data = await pr_collector.process_pr_url(identifier)
        jira_key = extract_jira_key_from_title(pr_data["title"])
        if jira_key:
            return jira_key
        else:
            # Auto-create Jira story from PR
            return await jira_client.create_issue_from_pr(pr_data)

    elif source == "api_spec":
        # Parse OpenAPI spec → NormalizedIssue per endpoint group
        return await spec_collector.process_spec_file(identifier)
```

### Source B: GitHub Pull Request

```
GitHub PR URL (e.g. https://github.com/org/repo/pull/3)
  → pr_collector.process_pr_url(url)         # Fetch PR title, body, labels
  → Check: Does PR title contain a Jira key?
      YES → Use that key (fetch from Jira)
      NO  → jira_client.create_issue(...)     # Auto-create Jira story
           → _get_active_sprint_id()          # Find active sprint
           → _add_issue_to_sprint(key, sprint) # Add to sprint
           → Proceed as Jira source
```

**Key detail:** If the PR title has no Jira key, Prism auto-creates a Jira Story from the PR title + bullet-point ACs, labels it `[PR #N] <title>`, and adds it to the active sprint. From this point, the pipeline runs **identically** to a Jira-triggered run.

### Source C: OpenAPI / Swagger Spec

```
YAML/JSON Spec File or URL
  → spec_collector.process_spec_file / process_spec_url
  → Extract: paths, HTTP methods, status codes, parameters, request bodies
  → Build NormalizedIssue per endpoint group
  → pipeline_runner.run_pipeline(issue)
```

The spec collector parses OpenAPI 2.0 / 3.0 specs, extracting API contract details into acceptance criteria for test generation. This means even if there is no Jira story or PR, a complete test suite can be generated purely from an API definition file.

### All Three Sources Converge

All three paths produce a `NormalizedIssue` and call `pipeline_runner.run_pipeline()`:

```python
@dataclass
class NormalizedIssue:
    key: str                        # e.g. ZT-3, ZT-29
    summary: str                    # Story/PR title
    description: str                # Full story text
    acceptance_criteria: list[str]  # Parsed AC bullet points
```

---

## 3. Webhook Listener — Auto-Trigger Pipeline

### 3.1 How It Works

The webhook listener is a single `aiohttp` server that accepts both Jira and GitHub webhook deliveries:

```
Jira Cloud ──────────POST /webhook/jira?secret=xxx──────────► localhost:5000
GitHub ──────────────POST /webhook/github───────────────────► localhost:5000
                             │
                    localtunnel (or ngrok)
                    public URL forwards to port 5000
```

**Startup:**
```bash
python -m src.integrations.webhook_listener   # Starts on port 5000
npx localtunnel --port 5000                   # Exposes publicly
```

### 3.2 Jira Webhook Handler

Triggered on `jira:issue_created` and `jira:issue_updated` events:

```python
async def jira_webhook_handler(request):
    # 1. Verify secret token in ?secret= query param
    secret = request.rel_url.query.get("secret", "")
    if secret != settings.jira_webhook_secret:
        return web.Response(status=401)

    # 2. Parse payload → extract issue key + event type
    payload = await request.json()
    event_type = payload.get("webhookEvent", "")
    issue_key = payload.get("issue", {}).get("key", "")

    # 3. On jira:issue_created or jira:issue_updated:
    if event_type in {"jira:issue_created", "jira:issue_updated"} and issue_key:
        asyncio.create_task(
            run_pipeline_in_background(source="jira", identifier=issue_key)
        )

    return web.Response(status=200, text="OK")
```

**Security:** Jira webhooks use a shared secret token in the query string. Register at: Jira → System → Webhooks → `https://<url>/webhook/jira?secret=<JIRA_WEBHOOK_SECRET>`

### 3.3 GitHub Webhook Handler

Triggered on PR events using HMAC-SHA256 signature validation:

```python
async def github_webhook_handler(request):
    # 1. Verify HMAC-SHA256 signature (X-Hub-Signature-256 header)
    signature = request.headers.get("X-Hub-Signature-256", "")
    body = await request.read()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return web.Response(status=403)

    # 2. Parse payload → extract event type, action, PR URL
    payload = json.loads(body)
    action = payload.get("action", "")
    pr_url = payload.get("pull_request", {}).get("html_url", "")

    # 3. Trigger on relevant PR actions
    if action in {"opened", "reopened", "synchronize", "edited", "ready_for_review"}:
        asyncio.create_task(
            run_pipeline_in_background(source="github_pr", identifier=pr_url)
        )

    return web.Response(status=200, text="OK")
```

**Security:** GitHub webhooks use HMAC-SHA256 signature verification. The listener validates every delivery. Register at: GitHub → Repo → Settings → Webhooks → `https://<url>/webhook/github`.

### 3.4 Background Execution Model

Pipeline runs are fired as `asyncio.create_task()` — the webhook handler returns HTTP 200 immediately, and the full pipeline (30–90 seconds) runs in the background. This prevents GitHub/Jira from retrying due to timeout.

```python
async def run_pipeline_in_background(source: str, identifier: str):
    try:
        result = await run_enhanced_pipeline_async(source, identifier)
        logger.info(f"Pipeline completed for {identifier}: {result['issue_key']}")
    except Exception as e:
        logger.error(f"Pipeline failed for {identifier}: {e}")
```

---

## 4. GitHub PR Path — Auto-Create Jira Story

### 4.1 PR Body Parsing (Acceptance Criteria Extraction)

When a PR has no Jira key, Prism parses its description for bullet-point ACs:

```python
# src/collector/pr_collector.py

body = pr_data.get("description", "") or ""
ac_lines = [
    line.lstrip("-•* ").strip()
    for line in body.splitlines()
    if line.strip().startswith(("-", "•", "*")) and len(line.strip()) > 2
]
```

Example PR body:
```markdown
Adds a remember me checkbox to the login form.

Acceptance Criteria:
- User can check remember me checkbox on login page
- Login button submits credentials with remember me option
- Valid email and password logs user in successfully
```

Becomes ACs: `["User can check remember me checkbox on login page", "Login button submits...", ...]`

### 4.2 Jira Story Creation

```python
# Summary: "[PR #3] Add remember me option to login"
# Description includes GitHub URL + PR body
ikey = jira.create_issue(
    summary=f"[PR #{pr_number}] {pr_title}",
    description=f"Auto-created from GitHub PR #{pr_number}: {pr_url}\n\n{body}",
    acceptance_criteria=ac_lines,
)
```

The Jira REST API endpoint for issue creation is `POST /rest/api/3/issue`. The request body is formatted per the Atlassian Document Format (ADF) for description and acceptance criteria fields.

### 4.3 Active Sprint Assignment

After creating the story, Prism automatically adds it to the active sprint:

```python
# src/integrations/jira_client.py

def _get_active_sprint_id(project_key: str) -> Optional[int]:
    # GET /rest/agile/1.0/board?projectKeyOrId=ZT&type=scrum
    # GET /rest/agile/1.0/board/{board_id}/sprint?state=active
    boards = self._get(f"/rest/agile/1.0/board?projectKeyOrId={project_key}&type=scrum")
    board_id = boards["values"][0]["id"]
    sprints = self._get(f"/rest/agile/1.0/board/{board_id}/sprint?state=active")
    return sprints["values"][0]["id"] if sprints["values"] else None

def _add_issue_to_sprint(issue_key: str, sprint_id: int):
    # POST /rest/agile/1.0/sprint/{sprint_id}/issue
    self._post(f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"issues": [issue_key]})
```

Sprint assignment is non-fatal — if no active sprint exists, the issue lands in the backlog and the pipeline continues.

---

## 5. AI Engine — Groq LLaMA Test Generation

### 5.1 Primary: Groq LLaMA (Online)

Prism calls the Groq API with `llama-3.3-70b-versatile` to generate structured test cases from the normalized issue:

```python
# src/ai_engine/ai_test_generator.py

prompt = f"""
You are a QA engineer. Generate test cases for this Jira story.

Issue: {issue.key}
Summary: {issue.summary}
Description: {issue.description}
Acceptance Criteria:
{chr(10).join(f"- {ac}" for ac in issue.acceptance_criteria)}

Generate 5-7 test cases in this JSON format:
[
  {{
    "title": "User successfully logs in with valid credentials",
    "type": "positive",
    "priority": "P1",
    "steps": [
      {{"step": "Navigate to login page", "data": "http://localhost:3000"}},
      {{"step": "Enter username", "data": "testuser"}},
      {{"step": "Enter password", "data": "password123"}},
      {{"step": "Click Login button", "data": ""}},
    ],
    "expected_result": "User is logged in and redirected to dashboard"
  }}
]
Include: positive, negative, boundary, UI validation, and risk-based cases.
"""

response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=4096,
    temperature=0.3,   # Low temperature for consistent, structured output
)
```

**Why temperature 0.3?** Higher temperatures produce varied but less consistent JSON. 0.3 gives enough creativity to cover multiple test types while remaining structured enough to parse reliably.

**Key differences vs raw API calls:**

| Dimension | Prism Approach | Naive Approach |
|---|---|---|
| Model | `llama-3.3-70b-versatile` — 70B param for richer reasoning | Smaller models miss edge cases |
| Temperature | 0.3 — controlled creativity | 1.0 → unparseable/verbose outputs |
| Prompt structure | Issue key + Summary + ACs as structured input | Unstructured paragraph → poor test variety |
| Output format | Strict JSON schema required in prompt | Free-form text → requires regex parsing |
| Retry logic | 3 attempts with exponential backoff | Single attempt → fails on rate limits |

### 5.2 Fallback: Rule-Based Generator (Offline)

If Groq fails (rate limit, no API key), the `RuleBasedTestGenerator` produces deterministic test cases:

```python
# src/ai_engine/rule_based_generator.py

class RuleBasedTestGenerator:
    def generate(self, issue: NormalizedIssue) -> list[dict]:
        test_cases = []

        for i, ac in enumerate(issue.acceptance_criteria):
            # 1 positive test per AC
            test_cases.append({
                "title": f"Verify: {ac}",
                "type": "positive",
                "priority": "P2",
                "steps": self._generate_steps_from_ac(ac),
                "expected_result": ac,
            })

        # Always add baseline negative and boundary tests
        test_cases.append(self._missing_required_fields_test(issue))
        test_cases.append(self._boundary_values_test(issue))

        return test_cases
```

### 5.3 Test Case Types Generated

| Type | Example |
|---|---|
| `positive` | Valid credentials → login succeeds |
| `negative` | Empty password → error shown |
| `boundary` | Password exactly at min length → passes |
| `ui_validation` | Login button is visible and enabled |
| `risk_based` | SQL injection in email field → rejected |

### 5.4 AI Retry Logic

Failed Groq calls are retried with exponential back-off:

```python
MAX_AI_RETRIES = 3
AI_RETRY_DELAY_SECONDS = 2.0

for attempt in range(MAX_AI_RETRIES):
    try:
        response = groq_client.chat.completions.create(...)
        break  # Success
    except Exception as e:
        if attempt < MAX_AI_RETRIES - 1:
            await asyncio.sleep(AI_RETRY_DELAY_SECONDS * (2 ** attempt))
            # Attempt 1 → wait 2s → Attempt 2 → wait 4s → Attempt 3 → fallback
        else:
            logger.warning("Groq failed after retries — using rule-based generator")
            return rule_based_generator.generate(issue)
```

### 5.5 JSON Extraction from LLM Response

The LLM response often contains markdown fences around the JSON. A robust extraction function handles this:

```python
def extract_json_from_response(text: str) -> list[dict]:
    # Strategy 1: Direct JSON parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code block
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return json.loads(match.group(1))

    # Strategy 3: Find first [ ... ] block
    start = text.find("[")
    end = text.rfind("]") + 1
    if start != -1 and end > start:
        return json.loads(text[start:end])

    raise ValueError("No valid JSON array found in LLM response")
```

---

## 6. Test Validator

### 6.1 Schema Validation

Each AI-generated test case is checked against a required schema:

```python
# src/validator/test_validator.py

REQUIRED_FIELDS = {"title", "type", "priority", "steps", "expected_result"}
VALID_TYPES = {"positive", "negative", "boundary", "ui_validation", "risk_based"}
VALID_PRIORITIES = {"P1", "P2", "P3"}

def validate_test_case(tc: dict) -> bool:
    # Check all required fields present
    if not REQUIRED_FIELDS.issubset(tc.keys()):
        logger.warning(f"Missing fields in test case: {REQUIRED_FIELDS - tc.keys()}")
        return False

    # Check type is valid
    if tc["type"] not in VALID_TYPES:
        logger.warning(f"Invalid test type: {tc['type']}")
        return False

    # Check priority is valid
    if tc["priority"] not in VALID_PRIORITIES:
        logger.warning(f"Invalid priority: {tc['priority']}")
        return False

    # Check steps is a non-empty list
    if not isinstance(tc["steps"], list) or len(tc["steps"]) == 0:
        logger.warning("Steps must be a non-empty list")
        return False

    return True
```

Malformed cases (missing fields, wrong types) are skipped with a warning and not published.

### 6.2 Deduplication

Duplicate test titles within the same run are removed before publishing:

```python
seen_titles: set[str] = set()
unique_cases: list[dict] = []

for tc in test_cases:
    if tc["title"] not in seen_titles:
        unique_cases.append(tc)
        seen_titles.add(tc["title"])
    else:
        logger.debug(f"Duplicate test case removed: {tc['title']}")
```

---

## 7. Zephyr Scale Publisher

### 7.1 Test Cycle Creation

For each pipeline run, a new test cycle is created in Zephyr Scale:

```python
# src/integrations/zephyr_client.py

# POST /rest/atm/1.0/testrun (Zephyr Scale Cloud v2 API)
cycle = zephyr_client.create_test_cycle(
    project_key="ZT",
    name=f"{issue_key} — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    jira_project_version=issue_key,
)
# Returns: { "id": 72937109, "key": "ZT-R81" }
```

### 7.2 Test Case + Execution Publishing

For each validated test case:

```python
# 1. Create test case
test_case = zephyr_client.create_test_case(
    project_key="ZT",
    name=tc["title"],
    steps=tc["steps"],
    priority=tc["priority"],
    issue_key=issue_key,
)
# Returns: { "key": "ZT-T425" }

# 2. Link to cycle
zephyr_client.create_test_execution(
    project_key="ZT",
    test_case_key="ZT-T425",
    test_cycle_key="ZT-R81",
    status="Not Executed",
)

# 3. After execution, update with result
zephyr_client.update_test_execution(
    execution_id=2843148654,
    status="Pass",  # or "Fail"
)
```

### 7.3 Zephyr API Authentication

Zephyr Scale Cloud uses Bearer token authentication, distinct from the Jira Basic Auth:

```python
headers = {
    "Authorization": f"Bearer {settings.zephyr_api_token}",
    "Content-Type": "application/json",
}
# Base URL: https://prod-api.zephyr4jiracloud.com/v2/
```

### 7.4 Dry Run Mode

When `ZEPHYR_DRY_RUN=true`, the publisher logs all API calls without making them — useful for testing the pipeline without polluting Zephyr:

```python
def create_test_case(self, **kwargs) -> dict:
    if self.dry_run:
        logger.info(f"[DRY RUN] Would create test case: {kwargs['name']}")
        return {"key": f"ZT-T{random.randint(1000, 9999)}"}  # Fake key
    # ... actual API call
```

---

## 8. Automation Generator — Playwright Script Generation

### 8.1 How Each Test Case Becomes a `.spec.js` File

For each validated test case, the `AutomationGenerator` produces a Playwright `.spec.js` file:

```javascript
// generated_tests/ZT-3_ZT-3-TC-001-POSITIVE.spec.js

const { test, expect } = require('@playwright/test');

test('User successfully logs in with valid credentials', async ({ page }) => {
  await page.goto('http://localhost:3000');

  // Step 1: Fill username
  await page.getByRole('textbox', { name: /username/i })
            .fill('testuser');

  // Step 2: Fill password
  await page.getByRole('textbox', { name: /password/i })
            .fill('password123');

  // Step 3: Click login
  await page.getByRole('button', { name: /login/i })
            .click();

  // Expected: User is logged in
  await expect(page.getByText(/protected content/i)).toBeVisible();
});
```

### 8.2 Action → Playwright Selector Strategy

The generator translates natural-language step strings into robust Playwright selectors:

| Step String Pattern | Generated Playwright Code |
|---|---|
| `fill.*email` | `page.getByRole('textbox', { name: /email/i }).fill(value)` |
| `click.*button` | `page.getByRole('button', { name: /keyword/i }).click()` |
| `click.*link` | `page.getByRole('link', { name: /keyword/i }).click()` |
| `navigate to /path` | `page.goto('http://localhost:3000/path')` |
| `verify.*visible` | `expect(page.getByText(/text/i)).toBeVisible()` |
| `select.*dropdown` | `page.getByRole('combobox', { name: /label/i }).selectOption(value)` |

**Why `getByRole` instead of CSS selectors:** Robust to DOM restructuring, matches the accessible name shown to users, and prevents "target closed" context errors that occur with generic `.click('a')` selectors.

### 8.3 File Naming Convention

```
{issue_key}_{issue_key}-TC-{sequence}-{TYPE}.spec.js

Example:
ZT-3_ZT-3-TC-001-POSITIVE.spec.js
ZT-3_ZT-3-TC-002-NEGATIVE.spec.js
ZT-3_ZT-3-TC-003-BOUNDARY.spec.js
```

This naming convention makes it easy to:
- Group all tests for an issue by filtering on `ZT-3_`
- Identify test type from the suffix
- Sort tests by their sequence number

### 8.4 Navigation Handling

After navigation-triggering clicks (links, form submits), the generator adds a `waitForLoadState`:

```javascript
await page.getByRole('link', { name: /forgot password/i }).click();
await page.waitForLoadState('networkidle');
// Now interact with the next page
```

### 8.5 Supported Frameworks

The generator supports four frameworks — selectable via `--framework` CLI flag:

| Framework | Output | File Extension |
|---|---|---|
| `playwright` (default) | Playwright Test API | `.spec.js` |
| `cypress` | Cypress `cy.` API | `.spec.js` |
| `nightwatch` | Nightwatch.js API | `.spec.js` |
| `gherkin` | Cucumber BDD Feature | `.feature` |

Each framework adapter lives in `src/codegen/`:

```
src/codegen/
├── automation_generator.py   ← Dispatcher + common logic
├── playwright_generator.py   ← Playwright Test API
├── cypress_generator.py      ← Cypress API
├── nightwatch_generator.py   ← Nightwatch.js API
└── gherkin_generator.py      ← Cucumber .feature format
```

---

## 9. Test Executor

### 9.1 Playwright Execution

The executor runs the generated `.spec.js` files for the current issue:

```python
# src/executor/test_executor.py

cmd = [
    "npx", "playwright", "test",
    "ZT-3_ZT-3-TC-001-POSITIVE.spec.js",
    "ZT-3_ZT-3-TC-002-POSITIVE.spec.js",
    # ... all spec files for this issue
    "--config", "playwright.config.js",
    "--ui",                        # Opens Playwright UI (visible browser)
    "--reporter=json",             # Also writes playwright-results.json
]
subprocess.run(cmd, cwd=project_root)
```

**UI Mode:** The executor uses `--ui` so the user can see tests running in a real browser window — tests fill fields, click buttons, and close automatically.

### 9.2 JSON-Based Result Parsing

The `--reporter=json` flag writes `playwright-results.json`. The executor reads this file for accurate pass/fail counts instead of parsing terminal output (which is unreliable in UI mode):

```python
def _run_and_parse_with_json(cmd, issue_key, json_report_path):
    subprocess.run(cmd)

    with open(json_report_path) as f:
        report = json.load(f)

    passed = 0
    failed = 0

    # Count from the JSON report
    for suite in report.get("suites", []):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                if test["status"] == "passed":
                    passed += 1
                else:
                    failed += 1

    return {"passed": passed, "failed": failed, "total": passed + failed}
```

### 9.3 Mock Server

Playwright tests run against `http://localhost:3000`, served by `mock-server.js` (Express):

| Endpoint | Description |
|---|---|
| `GET /` | Login page (`#username`, `#password`, `#login-btn`, `Forgot Password` link) |
| `POST /api/login` | Auth — accepts `testuser` / `password` |
| `GET /reset-password` | Reset password form (`#email`, `#send-reset-btn`) |
| `POST /api/reset-password` | Mock send reset email |
| `GET /boundary-test` | Boundary testing page |

The mock server is started automatically by Playwright via `playwright.config.js`:
```javascript
webServer: {
  command: 'node mock-server.js',
  url: 'http://localhost:3000',
  reuseExistingServer: true,
}
```

**Why a mock server?** Real applications aren't always available in CI or development environments. The mock server provides predictable endpoints so tests can run anywhere without external dependencies.

### 9.4 Result Upload to Zephyr

After execution, pass/fail results are uploaded for each test case:

```python
for i, tc in enumerate(executed_test_cases):
    result = execution_results[i]
    zephyr_client.update_test_execution(
        execution_id=tc["execution_id"],
        status="Pass" if result["status"] == "passed" else "Fail",
        comment=result.get("error_message", ""),
    )
```

---

## 10. Feedback Loop & Metrics Dashboard

### 10.1 Feedback Store

Failed test executions are logged to a feedback store for future AI improvement:

```python
# src/feedback/feedback_store.py

feedback_store.log_failure(
    issue_key=issue_key,
    test_title=tc["title"],
    error=error_message,
    generated_code=spec_js_content,
)
```

The feedback store persists to `data/feedback_log.json`. This data can be used to:
- Identify patterns in failing tests (e.g., certain selector strategies that don't work)
- Detect flaky tests (tests that sometimes pass and sometimes fail)
- Fine-tune the AI prompt to avoid generating problematic patterns

### 10.2 Dashboard Data

After every run, metrics are written to `data/dashboard_data.json`:

```json
{
  "coverage": {
    "total_issues_processed": 18,
    "total_tests_generated": 90,
    "total_tests_executed": 72,
    "total_passed": 68,
    "total_failed": 4,
    "overall_pass_rate": 94.4
  },
  "test_type_distribution": {
    "positive": 36,
    "negative": 27,
    "boundary": 18,
    "ui_validation": 9
  },
  "priority_distribution": {
    "P1": 45,
    "P2": 36,
    "P3": 9
  }
}
```

### 10.3 Dashboard HTML

The `dashboard.html` file at the project root renders the metrics data from `data/dashboard_data.json` as a live dashboard. Key metrics displayed:

- Overall pass rate (gauge chart)
- Test type distribution (pie/donut chart)
- Priority breakdown (bar chart)
- Per-issue test counts and execution history

---

## 11. PII Protection Layer

### 11.1 Detection Before LLM Submission

Before any data is sent to the Groq API, the PII detector scans the prompt:

```python
# src/ai_engine/pii_detector.py

PII_PATTERNS = {
    "email":       r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone":       r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn":         r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card": r"\b(?:\d[ -]?){13,16}\b",
    "ip_address":  r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
}

def mask_pii(text: str) -> str:
    for pii_type, pattern in PII_PATTERNS.items():
        text = re.sub(pattern, f"[{pii_type.upper()}_REDACTED]", text, flags=re.IGNORECASE)
    return text
```

Example: `"email: john@example.com"` → `"email: [EMAIL_REDACTED]"`

### 11.2 Why This Matters

Jira stories and PR descriptions frequently contain developer email addresses, staging server IPs, or sample user data. Sending these to a cloud LLM API without masking is a data governance risk. The PII layer ensures only the semantic intent of requirements reaches the model — not the actual sensitive values.

---

## 12. Backend CLI & API Architecture

### 12.1 CLI Entry Point

The main pipeline is invoked via CLI:

```bash
python -m src.pipeline.enhanced_pipeline <source> <identifier> [options]
```

| Flag | Default | Description |
|---|---|---|
| `--framework` | `playwright` | Automation framework (playwright, nightwatch, cypress, gherkin) |
| `--max-retries` | `3` | AI generation retry attempts |
| `--retry-delay` | `2.0` | Seconds between retries |
| `--team` | `None` | Optional team name tag for dashboard grouping |

### 12.2 Module Responsibilities

| Module | Responsibility |
|---|---|
| `src/pipeline/enhanced_pipeline.py` | CLI entry — resolves source type, dispatches to pipeline_runner |
| `src/pipeline/pipeline_runner.py` | Core orchestration: fetch → AI → validate → publish → codegen → execute |
| `src/integrations/jira_client.py` | Jira REST API: fetch issue, create story, sprint management |
| `src/integrations/zephyr_client.py` | Zephyr Scale API: test cycles, cases, executions, result upload |
| `src/integrations/webhook_listener.py` | aiohttp server — Jira + GitHub webhook endpoint |
| `src/integrations/github_client.py` | GitHub API client for PR fetching |
| `src/collector/pr_collector.py` | PR body parser — extracts Jira key + bullet ACs |
| `src/collector/spec_collector.py` | OpenAPI/Swagger spec parser |
| `src/ai_engine/ai_test_generator.py` | Groq LLaMA generation + rule-based fallback |
| `src/ai_engine/pii_detector.py` | PII detection and masking |
| `src/validator/test_validator.py` | Schema validation + deduplication |
| `src/codegen/automation_generator.py` | TestCase[] → Playwright/Cypress/Nightwatch/Gherkin scripts |
| `src/executor/test_executor.py` | Run specs, parse JSON report, return pass/fail |
| `src/feedback/feedback_store.py` | Log failed tests for feedback loop |
| `src/dashboard/metrics_tracker.py` | Write dashboard_data.json after each run |

---

## 13. Complete Pipeline Flow

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────────┐
│   Jira Cloud     │   │  GitHub PR       │   │  OpenAPI Spec            │
│  (story created/ │   │  (PR opened/     │   │  (YAML/JSON file or URL) │
│   updated event) │   │   edited event)  │   │                          │
└────────┬─────────┘   └────────┬─────────┘   └────────────┬─────────────┘
         │                      │                           │
         │ Webhook              │ Webhook                   │ CLI
         ▼                      ▼                           │
┌─────────────────────────────────────┐                     │
│   webhook_listener.py (port 5000)   │                     │
│   aiohttp server — Jira + GitHub    │                     │
└────────────────────┬────────────────┘                     │
                     │                                       │
                     ▼                                       ▼
          ┌──────────────────────────────────────────────────────────┐
          │           enhanced_pipeline.py                            │
          │   _resolve_issue_key(identifier) → NormalizedIssue key   │
          │                                                          │
          │   GitHub PR path:                                        │
          │     ├─ Has Jira key in title? → use that key             │
          │     └─ No key? → create_issue() → add to sprint          │
          └────────────────────────┬─────────────────────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │   jira_client.py          │
                    │   fetch_issue(key)        │
                    │   → NormalizedIssue       │
                    │   (summary + ACs)         │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │   pii_detector.py         │
                    │   Mask sensitive values   │
                    │   before LLM submission   │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │   ai_test_generator.py    │
                    │   Groq llama-3.3-70b      │
                    │   → TestCase[] (5-7 cases)│
                    │   + RuleBased fallback    │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │   validator.py            │
                    │   Schema check            │
                    │   + Deduplication         │
                    └──────────────┬────────────┘
                                   │
                     ┌─────────────┼──────────────┐
                     │             │              │
                     ▼             ▼              ▼
              zephyr_client   automation_    feedback_
              create cycle    generator     store
              create cases    .spec.js      log failures
              create execs    per TC
                     │
                     ▼
              test_executor.py
              npx playwright test
              --ui --reporter=json
              parse results JSON
                     │
                     ▼
              zephyr_client
              update executions
              Pass / Fail
                     │
                     ▼
              dashboard_data.json
              Metrics + coverage
```

---

## 14. Performance Metrics

Based on the current implementation and real pipeline runs:

| Metric | Value |
|---|---|
| Average pipeline time (Jira source) | 30–90 seconds |
| Average tests generated per story | 5–7 |
| Test types per run | positive, negative, boundary, UI, risk |
| Overall pass rate (mock server) | ~94% |
| AI retry success rate | >95% within 3 attempts |
| Zephyr API latency (per test case) | ~200–400 ms |
| Webhook response time | < 200 ms (pipeline in background) |
| Frameworks supported | 4 (Playwright, Cypress, Nightwatch, Gherkin) |

### Key Design Principles

1. **Fail-safe:** Every critical step (Groq API, Zephyr API, Playwright execution) has a fallback path or non-fatal error handling.
2. **Traceable:** Every generated test is linked to its Jira story in Zephyr Scale with a unique key.
3. **Immediate webhook response:** Webhook handlers always return HTTP 200 within milliseconds; the heavy pipeline work runs in the background.
4. **PII-safe:** No sensitive data from Jira stories or PR bodies reaches the cloud LLM.
5. **Framework-agnostic output:** The same AI-generated test cases can be exported to four different automation frameworks.
