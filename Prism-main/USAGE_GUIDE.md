# Prism Usage Guide

## Quick Start

### Basic Pipeline (Generate & Publish Only)

```bash
python -m src.pipeline.pipeline_runner ZT-3
```

This runs the basic pipeline:
- Fetches Jira issue
- Generates AI test cases
- Validates test cases
- Publishes to Zephyr

### Enhanced Pipeline (Full Automation)

```bash
# Generate automation code and execute tests
python -m src.pipeline.enhanced_pipeline ZT-3 --framework playwright --execute

# Generate automation code only (no execution)
python -m src.pipeline.enhanced_pipeline ZT-3 --framework playwright

# Skip automation generation
python -m src.pipeline.enhanced_pipeline ZT-3 --no-automation
```

## Component Usage

### 1. Automation Code Generation

```python
from src.codegen import AutomationGenerator

# Generate Playwright tests
generator = AutomationGenerator(framework="playwright", output_dir="generated_tests")
results = generator.generate_from_test_cases(
    validated_test_cases,
    issue_key="ZT-3",
    base_url="http://localhost:3000"
)

# Results contain file paths
for result in results:
    print(f"Generated: {result['file_path']}")
```

### 2. Test Execution

```python
from src.executor import TestExecutor

executor = TestExecutor(framework="playwright", timeout=300)
execution_results = executor.execute_tests(
    test_files=["generated_tests/ZT-3_TC-001.spec.js"],
    issue_key="ZT-3",
    output_dir="test_results"
)

print(f"Passed: {execution_results['passed']}")
print(f"Failed: {execution_results['failed']}")
```

### 3. Result Syncing

```python
from src.executor.result_syncer import ResultSyncer

syncer = ResultSyncer()
test_case_mapping = {
    "ZT-3_TC-001": "ZEPHYR-ZT-3-001"  # Map test file to Zephyr key
}
sync_results = syncer.sync_execution_results(execution_results, test_case_mapping)
```

### 4. Feedback Analysis

```python
from src.feedback import FeedbackAnalyzer

analyzer = FeedbackAnalyzer()

# Record execution feedback
analyzer.record_execution_feedback(issue_key, test_cases, execution_results)

# Record defect
analyzer.record_defect_feedback(
    issue_key="ZT-3",
    defect_key="ZT-10",
    test_case_id="ZT-3-TC-001",
    defect_description="Login fails with special characters"
)

# Get improvement suggestions
suggestions = analyzer.get_improvement_suggestions(issue_key, acceptance_criteria)
```

### 5. Metrics & Dashboard

```python
from src.dashboard import MetricsTracker
from src.dashboard.dashboard_generator import generate_html_dashboard

tracker = MetricsTracker()

# Record metrics
tracker.record_test_generation(issue_key, test_cases, generation_time)
tracker.record_execution_metrics(issue_key, execution_results)

# Get coverage metrics
coverage = tracker.get_coverage_metrics(days=30)
print(f"Pass Rate: {coverage['overall_pass_rate']}%")

# Generate HTML dashboard
generate_html_dashboard("dashboard.html")
```

## CI/CD Integration

### GitHub Actions

The workflow file `.github/workflows/full_pipeline.yml` runs the complete pipeline:

1. **Automatic Trigger**: On push to main/develop branches
2. **Manual Trigger**: Use "workflow_dispatch" with issue key input
3. **Steps**:
   - Setup Python and Node.js
   - Install dependencies
   - Run enhanced pipeline
   - Upload test results and dashboard

### Manual Workflow Trigger

1. Go to GitHub Actions tab
2. Select "Full Prism Pipeline"
3. Click "Run workflow"
4. Enter Jira issue key (e.g., ZT-3)
5. Click "Run workflow"

## Configuration

### Environment Variables

Create a `.env` file:

```bash
# Required for AI generation
GEMINI_API_KEY=your_gemini_api_key

# Optional: Jira (falls back to mock if not provided)
JIRA_BASE_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your_email@example.com
JIRA_API_TOKEN=your_jira_token

# Optional: Zephyr (falls back to mock if not provided)
ZEPHYR_BASE_URL=https://api.zephyrscale.smartbear.com
ZEPHYR_API_TOKEN=your_zephyr_token
ZEPHYR_PUBLISH_ENABLED=true
ZEPHYR_DRY_RUN=false

# Application under test
APP_BASE_URL=http://localhost:3000

# Pipeline behavior
GENERATE_AUTOMATION=true
EXECUTE_TESTS=false  # Set to true to actually run tests
SYNC_RESULTS=true
AI_FALLBACK_ENABLED=true
```

## Output Files

### Generated Files

- `generated_tests/` - Automation test scripts (Playwright/Nightwatch/Cypress)
- `test_results/` - Test execution results and JUnit XML reports
- `data/zephyr_published/` - Zephyr publish snapshots
- `data/feedback_db.json` - Feedback and learning data
- `data/metrics_db.json` - Metrics and statistics
- `dashboard.html` - Visual dashboard

### Logs

- `logs/ai_test_generator.log` - AI generation logs
- `logs/jira_collector.log` - Jira collection logs
- `logs/test_validator.log` - Validation logs

## Examples

### Example 1: Generate and Publish Only

```bash
export GEMINI_API_KEY=your_key
python -m src.pipeline.enhanced_pipeline ZT-3 --no-automation
```

### Example 2: Full Pipeline with Execution

```bash
export GEMINI_API_KEY=your_key
export EXECUTE_TESTS=true
export APP_BASE_URL=https://staging.example.com
python -m src.pipeline.enhanced_pipeline ZT-3 --framework playwright --execute
```

### Example 3: Generate Nightwatch.js Tests

```bash
python -m src.pipeline.enhanced_pipeline ZT-3 --framework nightwatch
```

## Troubleshooting

### AI Generation Fails

- Check `GEMINI_API_KEY` is set correctly
- System will automatically fall back to rule-based generator
- Check logs in `logs/ai_test_generator.log`

### Test Execution Fails

- Ensure test framework is installed: `npm install -g playwright` (or nightwatch/cypress)
- Check `APP_BASE_URL` points to running application
- Review execution results in `test_results/`

### Zephyr Sync Fails

- Verify `ZEPHYR_API_TOKEN` is valid
- Check Zephyr API base URL is correct
- System falls back to mock mode if credentials missing

## Next Steps

1. **Set up environment variables** in `.env` file
2. **Run basic pipeline** to test Jira → AI → Zephyr flow
3. **Generate automation code** for a test issue
4. **Execute tests** (if application is available)
5. **View dashboard** by generating HTML: `python -c "from src.dashboard.dashboard_generator import generate_html_dashboard; generate_html_dashboard()"`

