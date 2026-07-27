"""Generates a standalone HTML run summary and opens it in a browser tab
at the end of a pipeline run (replaces terminal-only output)."""

from __future__ import annotations
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List


def _tc_card(tc: Dict[str, Any], zephyr_key: str) -> str:
    steps_html = "".join(
        f"<li><b>{s.get('action','')}</b> → {s.get('expected_result','')}</li>"
        for s in tc.get("steps", [])
    )
    return f"""
    <div class="tc-card">
      <div class="tc-header">
        <span class="badge type-{tc.get('type','')}">{tc.get('type','?').upper()}</span>
        <span class="badge prio">{tc.get('priority','?')}</span>
        <span class="zid">Zephyr: {zephyr_key}</span>
      </div>
      <h3>{tc.get('title','Untitled')}</h3>
      <p class="desc">{tc.get('description','')}</p>
      <ul class="steps">{steps_html}</ul>
    </div>"""


def _issue_block(issue_key: str, source: str, test_cases: List[Dict], zephyr_results: List[Dict]) -> str:
    zmap = {}
    for zr in zephyr_results or []:
        zmap[zr.get("test_case_key") or zr.get("key")] = zr
    cards = []
    for i, tc in enumerate(test_cases or []):
        zkey = "not published"
        if i < len(zephyr_results or []):
            zkey = (zephyr_results[i] or {}).get("test_case_key", "not published")
        cards.append(_tc_card(tc, zkey))
    return f"""
    <section class="issue-block">
      <h2>{issue_key} <span class="source">({source})</span></h2>
      {''.join(cards)}
    </section>"""


def generate_and_open_summary(result: Dict[str, Any], output_path: str = "run_summary.html") -> str:
    """Build the HTML summary from a pipeline result (single or batch) and open it."""
    blocks = []
    if "batch_results" in result:
        for item in result["batch_results"]:
            core = item.get("core_pipeline") or {}
            blocks.append(_issue_block(
                item.get("issue_key", "?"),
                item.get("source", "?"),
                core.get("generated_test_cases", []),
                core.get("zephyr_publish_results", []),
            ))
    else:
        core = result.get("core_pipeline", {})
        blocks.append(_issue_block(
            result.get("issue_key", "?"),
            result.get("source", "?"),
            core.get("generated_test_cases", []),
            core.get("zephyr_publish_results", []),
        ))

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Prism Run Summary</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f5f5f5;padding:20px;max-width:1100px;margin:0 auto}}
header{{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:24px;border-radius:10px;margin-bottom:24px}}
h1{{margin:0 0 6px}}
.issue-block{{background:#fff;border-radius:10px;padding:20px;margin-bottom:24px;box-shadow:0 2px 4px rgba(0,0,0,.1)}}
.source{{color:#888;font-weight:normal;font-size:.7em}}
.tc-card{{border:1px solid #eee;border-radius:8px;padding:14px;margin:12px 0}}
.tc-header{{display:flex;gap:8px;align-items:center;margin-bottom:6px}}
.badge{{padding:3px 10px;border-radius:12px;font-size:.75em;font-weight:bold;color:#fff;background:#667eea}}
.badge.prio{{background:#555}}
.zid{{margin-left:auto;font-size:.8em;color:#666}}
.desc{{color:#444;margin:6px 0}}
.steps li{{margin:4px 0;font-size:.9em}}
</style></head>
<body>
<header><h1>Prism Pipeline — Run Summary</h1><div>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div></header>
{''.join(blocks)}
</body></html>"""

    out = Path(output_path).resolve()
    out.write_text(html, encoding="utf-8")
    webbrowser.open(f"file://{out}")
    return str(out)