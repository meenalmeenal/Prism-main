# Prism Architecture: Pipeline Orchestration, AI Engine & Full Flow

> **Project:** Prism — AI-Powered Test Automation Framework
> **Stack:** Python 3.13 · Groq LLaMA (llama-3.3-70b-versatile) · Playwright · aiohttp · Jira Cloud · Zephyr Scale
> **Samsung PRISM @ IIIT Naya Raipur**
> This document covers the full pipeline architecture: input sources, AI engine integration, module topology, conversation flow, data flow, and key configuration.

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Three Input Paths](#2-the-three-input-paths)
3. [AI Engine Integration](#3-ai-engine-integration)
4. [Module Topology](#4-module-topology)
5. [Pipeline Execution Flow](#5-pipeline-execution-flow)
6. [Data Flow Diagram](#6-data-flow-diagram)
7. [Key Configuration](#7-key-configuration)

---

## 1. Overview

Prism is an AI-driven test automation framework that converts requirements into fully executed test suites and publishes results to Zephyr Scale. The core engine is the `pipeline_runner.py` orchestrator (`src/pipeline/pipeline_runner.py`), which:

1. Accepts a requirement source (Jira story key, GitHub PR URL, or OpenAPI spec path/URL).
2. Fetches and normalizes the requirement into a `NormalizedIssue` dataclass.
3. Masks PII patterns before LLM submission.
4. Sends the normalized issue to the Groq LLaMA API as a structured prompt for test generation.
5. Validates and deduplicates the returned `TestCase[]` array.
6. Publishes test cases and creates test executions in Zephyr Scale.
7. Generates automation scripts (`.spec.js` or `.feature` files) per test case.
8. Executes tests via Playwright and uploads pass/fail results back to Zephyr.
9. Writes run metrics to `data/dashboard_data.json` for the local dashboard.

**Supported automation frameworks:** Playwright (default), Cypress, Nightwatch.js, Cucumber/Gherkin.

---

## 2. The Three Input Paths

### Path A: Jira Issue (Primary)

```
Jira Issue Key (e.g. ZT-3)
  → jira_client.fetch_issue(key)
  → jira_client._normalize_issue(payload)    # → NormalizedIssue
  → pipeline_runner.run_pipeline(issue)
```

Fetches the story from `/rest/api/3/issue/{key}` (Basic Auth: email + API token). The `_normalize_issue()` method extracts the summary, description text, and bullet-point acceptance criteria from the Atlassian Document Format response.

### Path B: GitHub Pull Request

```
GitHub PR URL (e.g. https://github.com/org/repo/pull/3)
  → pr_collector.process_pr_url(url)         # Fetch PR title, body, labels
  → Check: Does PR title contain a Jira key?
      YES → jira_client.fetch_issue(key)
      NO  → jira_client.create_issue(title, body, ac_lines)
           → jira_client._get_active_sprint_id()
           → jira_client._add_issue_to_sprint(key, sprint_id)
           → Proceed identically to Path A
```

The GitHub PR path **auto-creates a Jira story** when no key is present in the PR title, ensuring all test cases remain traceable in Jira and Zephyr regardless of origin.

### Path C: OpenAPI / Swagger Spec

```
YAML/JSON Spec File or URL
  → spec_collector.process_spec_file(path)   # Local file
  → spec_collector.process_spec_url(url)     # Remote URL
  → Extract: paths, HTTP methods, status codes, parameters, request bodies
  → Build NormalizedIssue per endpoint group
  → pipeline_runner.run_pipeline(issue)
```

The spec collector parses OpenAPI 2.0 / 3.0 specs, building acceptance criteria from each endpoint's expected status codes, parameters, and response schemas.

### All Paths Converge

All three paths produce the same `NormalizedIssue` and call the shared `run_pipeline()` method:

```python
@dataclass
class NormalizedIssue:
    key: str                        # e.g. ZT-3, ZT-29
    summary: str                    # Story title / PR title / endpoint group
    description: str                # Full story description or spec endpoint detail
    acceptance_criteria: list[str]  # Parsed bullet-point ACs
```

---

## 3. AI Engine Integration

### Groq LLaMA Client Configuration

The test generation uses the Groq Python SDK with `llama-3.3-70b-versatile`:

```python
# From src/ai_engine/ai_test_generator.py

groq_client = Groq(api_key=settings.groq_api_key)

response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",   # 70B param — best quality for test diversity
    messages=[
        {"role": "user", "content": prompt}
    ],
    max_tokens=4096,
    temperature=0.3,                    # Low: consistent JSON structure
)
```

### Model Configuration

| Setting | Value | Purpose |
|---|---|---|
| `ai_provider` | `groq` | Primary AI provider |
| `groq_model` | `llama-3.3-70b-versatile` | Main generation model |
| `temperature` | `0.3` | Low temperature for structured JSON output |
| `max_tokens` | `4096` | Sufficient for 5-7 detailed test cases |
| `max_ai_retries` | `3` | Maximum retry attempts on API failure |
| `ai_retry_delay_seconds` | `2.0` | Base delay for exponential backoff |
| `ai_fallback_enabled` | `true` | Use rule-based generator if Groq fails |

### Message Processing

The Groq API response is a single `ChatCompletion` object. The pipeline extracts the test cases JSON from `response.choices[0].message.content` using a multi-strategy parser:

- **Strategy 1:** Direct `json.loads()` on the response content.
- **Strategy 2:** Extract JSON from a markdown ` ```json ``` ` code fence.
- **Strategy 3:** Find the first `[` … `]` block in the response.
- **Fallback:** Log a warning and invoke the rule-based generator.

---

## 4. Module Topology

All modules in `src/` are pure Python — no subprocesses for core logic (unlike MCP-based systems). The automation generator and executor do spawn subprocesses via `subprocess.run()` for Playwright/Cypress/Nightwatch CLI calls.

### 4.1 Jira Client (`src/integrations/jira_client.py`)

**Purpose:** All interaction with the Jira REST API.

**Key methods:**
- `fetch_issue(key)` → `NormalizedIssue` — fetches and normalizes a story
- `create_issue(summary, description, acceptance_criteria)` → `str` — creates a new Jira story
- `_get_active_sprint_id(project_key)` → `Optional[int]` — finds the active sprint
- `_add_issue_to_sprint(issue_key, sprint_id)` — adds a story to a sprint

**Authentication:** HTTP Basic Auth (`email:api_token` encoded in Base64), sent as `Authorization: Basic <b64>`.

### 4.2 AI Test Generator (`src/ai_engine/ai_test_generator.py`)

**Purpose:** LLM-powered test case generation with offline fallback.

**Flow:**
1. Receive `NormalizedIssue`
2. PII-mask the prompt via `pii_detector.mask_pii()`
3. Call Groq API with structured prompt
4. Parse JSON response → `list[dict]` (raw test cases)
5. On failure after retries: delegate to `RuleBasedTestGenerator`

**Allowed tools (rule-based fallback):**
- AC-to-positive-test mapping
- Missing-required-fields negative test
- Boundary-value edge case test

### 4.3 Webhook Listener (`src/integrations/webhook_listener.py`)

**Purpose:** Unified aiohttp HTTP server for Jira + GitHub webhook events.

```
┌────────────────────────────────────────────────────────────┐
│              Webhook Listener (aiohttp, port 5000)          │
│                                                            │
│   POST /webhook/jira?secret=xxx                            │
│        │ Validate shared secret → fire asyncio.create_task │
│        ▼                                                   │
│   POST /webhook/github                                     │
│        │ Validate HMAC-SHA256 → fire asyncio.create_task   │
│        ▼                                                   │
│   run_pipeline_in_background(source, identifier)           │
└────────────────────────────────────────────────────────────┘
```

**Security mechanisms:**
- Jira: Shared secret in query string (`?secret=<JIRA_WEBHOOK_SECRET>`)
- GitHub: HMAC-SHA256 signature in `X-Hub-Signature-256` header

### 4.4 Automation Generator (`src/codegen/automation_generator.py`)

**Purpose:** Convert `TestCase[]` into framework-specific automation scripts.

**Allowed output formats:**
- `playwright` — Playwright Test API (`.spec.js`)
- `cypress` — Cypress `cy.` API (`.spec.js`)
- `nightwatch` — Nightwatch.js API (`.spec.js`)
- `gherkin` — Cucumber BDD (`.feature`)

### 4.5 Test Executor (`src/executor/test_executor.py`)

**Purpose:** Run generated spec files via CLI subprocess and parse results.

```python
# Playwright execution command
cmd = [
    "npx", "playwright", "test",
    *spec_files,                   # All spec files for this issue
    "--config", "playwright.config.js",
    "--ui",                        # Visible browser mode
    "--reporter=json",             # Structured result output
]
subprocess.run(cmd, cwd=project_root)
```

**Result parsing:** Reads `playwright-results.json` for accurate pass/fail counts (terminal parsing unreliable in `--ui` mode).

### 4.6 Zephyr Client (`src/integrations/zephyr_client.py`)

**Purpose:** Publish and update test artifacts in Zephyr Scale Cloud.

**Allowed operations:**
- `create_test_cycle(project_key, name, ...)` → creates a new test run
- `create_test_case(project_key, name, steps, priority, issue_key)` → creates a test case
- `create_test_execution(project_key, test_case_key, test_cycle_key, status)` → links case to cycle
- `update_test_execution(execution_id, status, comment)` → sets Pass/Fail

**Authentication:** Bearer token (`Authorization: Bearer <ZEPHYR_API_TOKEN>`), distinct from Jira Basic Auth.

### Module Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                    Pipeline Execution                                │
│                                                                    │
│   NormalizedIssue (from Jira / PR / Spec)                          │
│        │                                                           │
│        ▼                                                           │
│   ┌─────────────────────────┐                                      │
│   │   pipeline_runner.py    │                                      │
│   └──────┬──────────────────┘                                      │
│          │ Orchestrates                                             │
│          ▼                                                         │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Pure Python Modules (no subprocess for core logic)       │    │
│   │                                                          │    │
│   │  ┌──────────────────┐  ┌─────────────────────────────┐  │    │
│   │  │  pii_detector    │  │  ai_test_generator           │  │    │
│   │  │  Mask before LLM │  │  Groq llama-3.3-70b          │  │    │
│   │  │                  │  │  + RuleBased fallback        │  │    │
│   │  └──────────────────┘  └─────────────────────────────┘  │    │
│   │                                                          │    │
│   │  ┌──────────────────┐  ┌─────────────────────────────┐  │    │
│   │  │  test_validator  │  │  zephyr_client               │  │    │
│   │  │  Schema check    │  │  Publish + update results    │  │    │
│   │  │  Deduplication   │  │                             │  │    │
│   │  └──────────────────┘  └─────────────────────────────┘  │    │
│   └──────────────────────────────────────────────────────────┘    │
│          │                                                         │
│          ▼                                                         │
│   ┌──────────────────────────────────────────────────────────┐    │
│   │  Subprocess-based Modules                                 │    │
│   │                                                          │    │
│   │  ┌──────────────────┐  ┌─────────────────────────────┐  │    │
│   │  │  automation_gen  │  │  test_executor               │  │    │
│   │  │  → .spec.js      │  │  npx playwright test         │  │    │
│   │  │  → .feature      │  │  Parse results JSON          │  │    │
│   │  └──────────────────┘  └─────────────────────────────┘  │    │
│   └──────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 5. Pipeline Execution Flow

The pipeline follows this sequence for every run:

### Phase 1: Requirement Resolution

`enhanced_pipeline.py` resolves the input source and identifier into a Jira issue key, then fetches the full `NormalizedIssue`:

```python
# enhanced_pipeline.py
issue_key = await _resolve_issue_key(source, identifier)
normalized_issue = await jira_client.fetch_issue(issue_key)
```

For GitHub PR inputs without a Jira key, this phase also:
1. Creates a new Jira story (`create_issue`)
2. Finds the active sprint (`_get_active_sprint_id`)
3. Adds the story to the sprint (`_add_issue_to_sprint`)

### Phase 2: PII Masking

Before constructing the LLM prompt, any PII patterns in the issue content are masked:

```python
masked_description = pii_detector.mask_pii(normalized_issue.description)
masked_acs = [pii_detector.mask_pii(ac) for ac in normalized_issue.acceptance_criteria]
```

Masked patterns: email addresses, phone numbers, SSNs, credit card numbers, IP addresses.

### Phase 3: AI Test Generation

The masked issue is sent to Groq with a structured prompt requesting 5-7 test cases in a strict JSON format. The prompt specifies:
- Issue key and summary for context
- Full description and acceptance criteria
- Required JSON schema with `title`, `type`, `priority`, `steps`, `expected_result`
- Instruction to include all five test types: positive, negative, boundary, UI validation, risk-based

```python
test_cases_raw = await ai_generator.generate(normalized_issue)
# Returns: list[dict] with raw LLM output
```

### Phase 4: Validation & Deduplication

Each raw test case is validated against the schema, and duplicate titles are removed:

```python
valid_cases = [tc for tc in test_cases_raw if validator.validate_test_case(tc)]
unique_cases = validator.deduplicate(valid_cases)
# Typically: 5-7 raw → 5-7 valid → 5-7 unique (near-zero duplicates from LLaMA)
```

### Phase 5: Zephyr Publishing

A test cycle is created for the run, then each test case is published with an initial "Not Executed" status:

```python
cycle = zephyr_client.create_test_cycle(project_key, name=f"{issue_key} — {timestamp}")

for tc in unique_cases:
    test_case = zephyr_client.create_test_case(project_key, tc["title"], tc["steps"], ...)
    execution = zephyr_client.create_test_execution(
        project_key, test_case["key"], cycle["key"], status="Not Executed"
    )
    tc["execution_id"] = execution["id"]
```

### Phase 6: Automation Code Generation

One spec file is generated per test case:

```python
for i, tc in enumerate(unique_cases):
    filename = f"{issue_key}_{issue_key}-TC-{i+1:03d}-{tc['type'].upper()}.spec.js"
    spec_code = automation_generator.generate(tc, framework=settings.framework)
    (generated_tests_dir / filename).write_text(spec_code)
```

### Phase 7: Test Execution

All spec files for this issue are executed in a single Playwright run:

```python
spec_files = [f for f in generated_tests_dir.iterdir()
              if f.name.startswith(issue_key)]

results = test_executor.run(spec_files, config="playwright.config.js")
# Returns: {"passed": N, "failed": M, "details": [...]}
```

### Phase 8: Result Upload

Pass/fail results are uploaded to Zephyr for each test execution:

```python
for tc, result in zip(unique_cases, results["details"]):
    zephyr_client.update_test_execution(
        tc["execution_id"],
        status="Pass" if result["status"] == "passed" else "Fail",
        comment=result.get("error", ""),
    )
```

### Phase 9: Metrics

Dashboard data is updated with the results of this run:

```python
metrics_tracker.record_run(
    issue_key=issue_key,
    generated=len(unique_cases),
    executed=results["total"],
    passed=results["passed"],
    failed=results["failed"],
    test_types={tc["type"] for tc in unique_cases},
)
# Writes updated data/dashboard_data.json
```

---

## 6. Data Flow Diagram

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────────┐
│   Jira Cloud     │   │  GitHub PR       │   │  OpenAPI Spec            │
│  (story created/ │   │  (PR opened/     │   │  (YAML/JSON file or URL) │
│   updated event) │   │   edited event)  │   │                          │
└────────┬─────────┘   └────────┬─────────┘   └────────────┬─────────────┘
         │                      │                           │
         │ Webhook / CLI        │ Webhook / CLI             │ CLI
         ▼                      ▼                           │
┌─────────────────────────────────────┐                     │
│   webhook_listener.py (port 5000)   │                     │
│   aiohttp — Jira + GitHub handlers  │                     │
└────────────────────┬────────────────┘                     │
                     │                                       │
                     └──────────────────┬────────────────────┘
                                        │
                                        ▼
                          ┌─────────────────────────┐
                          │  enhanced_pipeline.py    │
                          │  Resolve source →        │
                          │  NormalizedIssue         │
                          │                         │
                          │  (GitHub PR: may auto-   │
                          │   create Jira story +   │
                          │   add to active sprint) │
                          └─────────────┬───────────┘
                                        │
                    ┌───────────────────┼──────────────────────┐
                    │                   │                      │
                    ▼                   ▼                      ▼
             jira_client.py       pii_detector.py      dashboard metrics
             fetch_issue(key)     Mask PII in          recorded at end
             → NormalizedIssue    prompt text
                    │
                    ▼
             ai_test_generator.py
             Groq llama-3.3-70b
             → TestCase[] (5-7)
             + RuleBased fallback
                    │
                    ▼
             test_validator.py
             Schema check
             + Deduplication
                    │
          ┌─────────┼─────────────┐
          │         │             │
          ▼         ▼             ▼
   zephyr_client  automation_  feedback_
   create cycle   generator    store
   create cases   .spec.js     log failures
   create execs   per TC
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

## 7. Key Configuration

All settings are loaded from the `.env` file.

### Jira

| Variable | Default | Description |
|---|---|---|
| `JIRA_BASE_URL` | `""` | e.g. `https://yourorg.atlassian.net` |
| `JIRA_EMAIL` | `""` | Jira account email (Basic Auth username) |
| `JIRA_API_TOKEN` | `""` | Jira REST API token (from id.atlassian.com/manage/api-tokens) |
| `JIRA_PROJECT_KEY` | `ZT` | Default project key for new issues |
| `JIRA_WEBHOOK_SECRET` | `""` | Shared secret for Jira webhook validation |

### Zephyr Scale

| Variable | Default | Description |
|---|---|---|
| `ZEPHYR_BASE_URL` | `https://prod-api.zephyr4jiracloud.com/v2/` | Zephyr Cloud API base URL |
| `ZEPHYR_API_TOKEN` | `""` | Zephyr Scale bearer token |
| `ZEPHYR_PROJECT_KEY` | `ZT` | Project key (must match Jira project) |
| `ZEPHYR_DRY_RUN` | `false` | `true` = log API calls without sending |

### Groq AI

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | `""` | Groq API key (console.groq.com) |
| `AI_PROVIDER` | `groq` | AI provider (currently only `groq` supported) |
| `MAX_AI_RETRIES` | `3` | Number of retries on AI failure |
| `AI_RETRY_DELAY_SECONDS` | `2.0` | Delay between retries (doubles each attempt) |
| `AI_FALLBACK_ENABLED` | `true` | Use rule-based generator if Groq fails |

### GitHub

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | `""` | GitHub PAT (classic, `repo` scope) |
| `GITHUB_WEBHOOK_SECRET` | `""` | HMAC secret for GitHub webhook verification |

### Webhook Listener

| Variable | Default | Description |
|---|---|---|
| `WEBHOOK_PORT` | `5000` | Port the listener binds to |

### Automation & Execution

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_FRAMEWORK` | `playwright` | Automation framework (playwright, cypress, nightwatch, gherkin) |
| `PLAYWRIGHT_BASE_URL` | `http://localhost:3000` | Base URL for generated Playwright tests |

---

## Key Source Files

| File | Purpose |
|---|---|
| `src/pipeline/enhanced_pipeline.py` | Main CLI entry point — resolves source, dispatches to `pipeline_runner` |
| `src/pipeline/pipeline_runner.py` | Core orchestration: fetch → AI → validate → publish → codegen → execute |
| `src/integrations/jira_client.py` | Jira REST API: fetch issue, create story, find sprint, add to sprint |
| `src/integrations/zephyr_client.py` | Zephyr Scale API: create cycle, cases, executions, update results |
| `src/integrations/webhook_listener.py` | `aiohttp` server — Jira + GitHub webhook endpoint, background pipeline trigger |
| `src/integrations/github_client.py` | GitHub API client (PR fetching, token auth) |
| `src/collector/pr_collector.py` | GitHub PR body parser — extracts Jira key + bullet-point ACs |
| `src/collector/spec_collector.py` | OpenAPI/Swagger spec parser |
| `src/ai_engine/ai_test_generator.py` | Groq LLaMA test generation + rule-based fallback |
| `src/ai_engine/pii_detector.py` | PII detection and masking before LLM calls |
| `src/validator/test_validator.py` | Schema validation + deduplication of AI test cases |
| `src/codegen/automation_generator.py` | Converts `TestCase[]` into Playwright/Cypress/Nightwatch/Gherkin scripts |
| `src/executor/test_executor.py` | Runs generated specs, parses JSON report, returns pass/fail counts |
| `src/feedback/feedback_store.py` | Logs failed test cases for feedback loop |
| `src/dashboard/metrics_tracker.py` | Writes `data/dashboard_data.json` after each run |
| `mock-server.js` | Express server (port 3000) — login, reset-password, boundary-test pages |
| `playwright.config.js` | Playwright config — base URL, headless mode, test directory |
| `.env.example` | Template for all required environment variables |
