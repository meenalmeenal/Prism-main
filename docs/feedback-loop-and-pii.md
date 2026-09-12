# Feedback Loop, Metrics & PII Masking Reference

This document provides a technical reference for the feedback loop, metrics tracking, and PII masking subsystems on `main`.

---

## 1. Public API Changes & Additions

| Symbol | Location | Change Type | Description & Compatibility |
| :--- | :--- | :--- | :--- |
| `FeedbackStore.get_feedback_for_issue(issue_key, include_resolved=False)` | `src/feedback/feedback_store.py` | **BEHAVIOUR CHANGE** | Returns a list of `TestFeedback` records for the given issue key. **Resolved records are now excluded by default** unless `include_resolved=True` is explicitly passed. Existing callers expecting resolved records must pass `include_resolved=True` (e.g., `pipeline_runner._fetch_past_failures`). |
| `FeedbackStore.mark_resolved(test_case_id, resolved_at=None) -> bool` | `src/feedback/feedback_store.py` | **Additive** | Marks stored failure records matching `test_case_id` with `resolved=True` and an ISO-8601 timestamp (`resolved_at`). Idempotent; returns `True` if any record matched, `False` otherwise. Preserves on-disk history without deleting records. |
| `TestFeedback` | `src/feedback/feedback_store.py` | **Additive** | Dataclass representing stored feedback. Fields: `test_case_id: str`, `issue_key: str`, `error_message: str`, `test_steps: List[Dict]`, `timestamp: str`, `resolved: bool = False`, `resolved_at: Optional[str] = None`, `title: str = ""`. Default values ensure pre-existing stored JSON files load without errors. Sets `__test__ = False` to prevent pytest collection. |
| `PromptTemplates.get_test_generation_prompt(...)` | `src/ai_engine/prompt_templates.py` | **Additive** | Accepts optional `past_failures: Optional[List[Any]] = None` and `resolved_failures: Optional[List[Any]] = None`. When `None` or empty, prompt generation remains byte-identical. |
| `AITestGenerator.generate_test_cases(...)` | `src/ai_engine/ai_test_generator.py` | **Additive** | Accepts optional `past_failures` and `resolved_failures`, forwarding them to `PromptTemplates`. |
| `RuleBasedTestGenerator.generate_test_cases(...)` | `src/ai_engine/ai_test_generator.py` | **Additive** | Accepts optional `past_failures` and `resolved_failures` for signature parity with `AITestGenerator`; ignores them during offline rule-based generation. |
| `MetricsTracker.record_execution_metrics(...)` | `src/dashboard/metrics_tracker.py` | **Additive** | Persists `execution_results["per_test"]` in the recorded execution entry alongside aggregate test run statistics. |
| `MetricsTracker.get_flaky_test_report(n_runs=10)` | `src/dashboard/metrics_tracker.py` | **Additive** | Analyzes the last `n_runs` execution entries for tests exhibiting both `Pass` and `Fail` across $\ge 2$ valid runs. Returns a list of dicts with keys: `test_case_id`, `title`, `runs`, `pass_count`, `fail_count`, `flip_count`, `flaky_ratio`, `avg_duration_ms`, `last_status`. |
| `pii_masker.mask_pii(text, ...)` | `src/utils/pii_masker.py` | **Compatible** | Scans and redacts sensitive entities (credit cards with Luhn validation, emails, phone numbers, SSNs, Aadhaar, PAN, IBAN, IP addresses, credentials, contextual DOBs, physical addresses, names, sensitive URLs). Returns sanitized `str`. |
| `pii_masker.mask_pii_with_summary(text, ...) -> Tuple[str, Dict[str, int]]` | `src/utils/pii_masker.py` | **Additive** | Returns a tuple containing the masked text string and a dictionary of redaction counts per PII category. |

---

## 2. Behavioral Specifications

### Feedback Prompt Injection
- **Unresolved Failures**: Injected under `## Known past failures for this issue (learn from these)`. Capped at the **10 most recent** items (`past_failures[-10:]`). Error messages are trimmed to a maximum of **300 characters**.
- **Resolved Failures**: Injected under `## Previously fixed for this issue — do not reintroduce`. Capped at the **5 most recent** items (`resolved_failures[-5:]`). Error messages are trimmed to a maximum of **300 characters**.
- **Title Rendering**: The prompt builder prefers `title` for each bullet line and falls back to `test_case_id` if `title` is empty or missing:
  `- <title or test_case_id> — failed because: <error_message>`

### PII Masking Pipeline Separation
- **Source Sanitization**: `pipeline_runner._fetch_past_failures()` applies `mask_pii()` to `error_message`, `title`, and `test_steps` on detached copies via `dataclasses.replace()` or dict copies before injecting them into the AI prompt.
- **On-Disk Integrity**: The stored feedback records in `data/feedback.json` retain their original unmasked text for auditing and debugging; masking is applied at the prompt boundary to prevent fixture PII and runtime secrets from leaking to external LLM endpoints.
- **Resilient Error Logging**: Per-item masking failures log only the test case identifier (`test_case_id` or `<unknown>`), ensuring unmasked data is never written to log files.

### Flaky Test Calculation Metrics
- **`flip_count`**: The number of state transitions between consecutive runs for a given test case (e.g., `Pass` $\rightarrow$ `Fail` or `Fail` $\rightarrow$ `Pass`).
- **`flaky_ratio`**: Calculated as $\text{round}\left(\frac{\min(\text{pass\_count}, \text{fail\_count})}{\text{total\_valid\_runs}}, 2\right)$.
- **Empty State**: `get_flaky_test_report()` returns `[]` if no execution entries contain the `per_test` list.

---

## 3. Configuration & Optional Dependencies

### URL Masking Mode
Controlled via the `PII_URL_MASK_MODE` environment variable:
- `smart` (default): Redacts embedded user credentials (userinfo) and sensitive query parameters (e.g., `token`, `key`, `secret`, `session`, `password`, `api_key`), keeping the rest of the URL readable for context.
- `strict`: Replaces the entire URL with `[URL]`.
- `off`: Disables URL redaction completely.

### Named Entity Recognition (NER)
- `src/utils/pii_masker.py` uses heuristic title/label patterns and an extensive domain allowlist to avoid masking QA keywords, ticket keys (e.g., `ZT-123`), and testing tools.
- If `spacy` and the `en_core_web_sm` model are installed, the masker leverages SpaCy for additional person-name validation. If `spacy` is not installed, the masker falls back to rule-based detection without raising an error.
