# Prism: AI-Powered Test Case Generation

## Project Overview
Prism is an automated test case generator that fetches Jira issues, generates comprehensive test cases using Google Gemini AI, validates them, and publishes results. The pipeline transforms acceptance criteria into detailed, executable test cases across multiple test types.

## Architecture & Data Flow

**Five-Stage Pipeline:**

1. **Collection** (`src/collector/jira_collector.py`): Fetches Jira issues via Jira REST API v3
   - Uses HTTPBasicAuth with email + API token
   - Returns fields: summary, description, issuetype, status, priority

2. **AI Generation** (`src/ai_engine/`): Generates test cases using Google Gemini
   - `AITestGenerator`: Handles Gemini API communication
   - `PromptTemplates`: Separated prompt engineering logic
   - Generates 8-10 test cases per issue covering: positive, negative, boundary, UI validation, risk-based
   - **Critical**: Expects JSON array output from AI model

3. **Validation** (`src/validator/test_validator.py`): Cleans and scores test cases
   - Schema validation against required fields: `id`, `title`, `type`, `priority`, `preconditions`, `steps`, `tags`
   - Valid types: `['positive', 'negative', 'boundary', 'ui_validation', 'risk_based']`
   - Valid priorities: `['P1', 'P2', 'P3']`
   - Deduplication by ID and similar title matching
   - PII sanitization (SSN, credit card, phone patterns)
   - Quality scoring (flags scores < 60 for review)

4. **Code Generation** (`src/codegen/`): Generates automation code (future phase)

5. **Publishing** (`src/publisher/`): Publishes results to Zephyr Scale API (in progress)

## Key Patterns & Conventions

### Prompt Engineering
- Prompts are **separated from API code** for maintainability
- Prompt templates use markdown formatting with explicit JSON schema descriptions and examples
- Critical instruction: AI responses must be **pure JSON arrays with NO markdown/code blocks**
- Prompt includes realistic test data examples (emails, passwords) to guide AI output

### Error Handling & Logging
- **Consistent logging setup**: All modules create `logs/` directory and configure FileHandler + StreamHandler
- Error handling uses logging + exceptions (not silent failures)
- API failures catch specific HTTP errors (e.g., 404 for missing issues)

### Environment Configuration
- All credentials loaded from `.env` file using `python-dotenv`
- Required keys: `GEMINI_API_KEY`, `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `ZEPHYR_API_TOKEN`
- No hardcoded credentials or defaults

### Data Structures
- Test cases use consistent dictionary schema with nested steps array
- Each step: `step_number` (int), `action`, `test_data`, `expected_result`
- Test case IDs follow pattern: `[ISSUE_KEY]-TC-[NUMBER]-[TYPE]` (e.g., `ZT-3-TC-001-POSITIVE`)

### Import Strategy
- `PromptTemplates` has fallback imports handling: direct → module → src paths
- Supports both direct script execution and module imports

## Development Workflows

### Adding New AI Prompt Types
1. Add static method to `PromptTemplates` class (e.g., `get_refinement_prompt()`)
2. Follow JSON schema format: include schema description and example in prompt
3. Return raw prompt string (no API calls in templates)
4. Extend `AITestGenerator` with corresponding method calling the template

### Testing
- Use `pytest` for unit tests
- Test files: `test_zephyr.py` demonstrates API integration testing
- Mock/test data in `data/` directory (JSON files per issue)

### Extending Validation
- Add new validation rules to `TestValidator._validate_schema()` or new validation methods
- Update `REQUIRED_FIELDS` or `VALID_*` constants as needed
- Validation is multi-pass: schema → deduplication → PII → quality scoring

## Integration Points & Dependencies

- **Google Gemini**: `google.genai` library, models: `gemini-2.5-flash`
- **Jira API**: REST API v3, HTTPBasicAuth, fields from standard issue schema
- **Zephyr Scale**: API endpoint uses Bearer token (see `test_zephyr.py`)
- **External**: requests, python-dotenv, pyyaml, pytest

## Project-Specific Details

- **Issue Key Format**: Jira project typically uses `ZT-*` (Zephyr Testing project)
- **Test Data Artifacts**: JSON files stored in `data/` (e.g., `ZT-3.json`, `ZT-3_ai_tests.json`, `ZT-3_ai_tests_validated.json`)
- **Output Filenames**: Follow pattern `{ISSUE_KEY}_ai_tests.json` (raw) → `{ISSUE_KEY}_ai_tests_validated.json` (after validation)
- **Logs**: All logs written to `logs/` directory with module-specific files

## AI Agent Guidance

When extending this codebase:
- **Maintain separation of concerns**: Prompts separate from API logic, collectors separate from validators
- **Preserve logging patterns**: Always log at INFO for major operations, DEBUG for detailed traces
- **Test data structure**: Ensure AI outputs match the strict JSON schema (required fields, nested steps)
- **Validation first**: Test cases must pass schema validation before quality scoring
- **Error messages**: Include issue_key/context in error logs for debugging pipeline failures
