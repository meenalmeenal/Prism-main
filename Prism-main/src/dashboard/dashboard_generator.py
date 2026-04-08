"""Dashboard HTML generator.

Generates HTML dashboard for visualizing metrics and test coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from src.dashboard.metrics_tracker import MetricsTracker


def generate_html_dashboard(output_path: str = "dashboard.html") -> str:
    """Generate HTML dashboard from metrics.

    Parameters
    ----------
    output_path: str
        Path to save the HTML dashboard

    Returns
    -------
    str
        Path to generated HTML file
    """
    tracker = MetricsTracker()
    dashboard_data = tracker.generate_dashboard_data()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prism Test Automation Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .subtitle {{
            opacity: 0.9;
            font-size: 1.1em;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            padding: 25px;
            border-radius: 10px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .card h2 {{
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}
        .metric:last-child {{
            border-bottom: none;
        }}
        .metric-label {{
            color: #666;
        }}
        .metric-value {{
            font-size: 1.5em;
            font-weight: bold;
            color: #667eea;
        }}
        .progress-bar {{
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin-top: 10px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
        }}
        .status-badge {{
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }}
        .status-pass {{
            background: #4caf50;
            color: white;
        }}
        .status-fail {{
            background: #f44336;
            color: white;
        }}
        .status-flaky {{
            background: #ff9800;
            color: white;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #333;
        }}
        .footer {{
            text-align: center;
            color: #666;
            margin-top: 40px;
            padding: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 Prism Test Automation Dashboard</h1>
            <div class="subtitle">AI-Driven Test Case Generation & Execution Metrics</div>
            <div class="subtitle" style="margin-top: 10px;">Last Updated: {dashboard_data.get('last_updated', 'N/A')}</div>
        </header>

        <div class="grid">
            <div class="card">
                <h2>📊 Coverage Metrics (30 Days)</h2>
                <div class="metric">
                    <span class="metric-label">Issues Processed</span>
                    <span class="metric-value">{dashboard_data.get('coverage', {}).get('total_issues_processed', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Tests Generated</span>
                    <span class="metric-value">{dashboard_data.get('coverage', {}).get('total_tests_generated', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Tests Executed</span>
                    <span class="metric-value">{dashboard_data.get('coverage', {}).get('total_tests_executed', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Pass Rate</span>
                    <span class="metric-value">{dashboard_data.get('coverage', {}).get('overall_pass_rate', 0):.1f}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {dashboard_data.get('coverage', {}).get('overall_pass_rate', 0)}%">
                        {dashboard_data.get('coverage', {}).get('overall_pass_rate', 0):.1f}%
                    </div>
                </div>
            </div>

            <div class="card">
                <h2>✅ Execution Summary</h2>
                <div class="metric">
                    <span class="metric-label">Total Passed</span>
                    <span class="metric-value status-badge status-pass">{dashboard_data.get('coverage', {}).get('total_passed', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total Failed</span>
                    <span class="metric-value status-badge status-fail">{dashboard_data.get('coverage', {}).get('total_failed', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Coverage %</span>
                    <span class="metric-value">{dashboard_data.get('coverage', {}).get('coverage_percentage', 0):.1f}%</span>
                </div>
            </div>

            <div class="card">
                <h2>📈 Test Type Distribution</h2>
                {_generate_test_type_chart(dashboard_data.get('test_type_distribution', {}))}
            </div>

            <div class="card">
                <h2>🎯 Priority Distribution</h2>
                {_generate_priority_chart(dashboard_data.get('priority_distribution', {}))}
            </div>
        </div>

        <div class="card" style="margin-top: 20px;">
            <h2>⚠️ Flaky Tests</h2>
            {_generate_flaky_tests_table(dashboard_data.get('flaky_tests', []))}
        </div>
    </div>

    <div class="footer">
        <p>Generated by Prism AI Test Automation Framework</p>
        <p>© {datetime.now().year} - All rights reserved</p>
    </div>
</body>
</html>
"""

    output_file = Path(output_path)
    with output_file.open("w", encoding="utf-8") as f:
        f.write(html)

    return str(output_file)


def _generate_test_type_chart(test_types: Dict[str, int]) -> str:
    """Generate HTML for test type distribution chart."""
    if not test_types:
        return "<p style='color: #999;'>No data available</p>"

    total = sum(test_types.values())
    html = ""
    for test_type, count in sorted(test_types.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total * 100) if total > 0 else 0
        html += f"""
        <div class="metric">
            <span class="metric-label">{test_type.replace('_', ' ').title()}</span>
            <span class="metric-value">{count}</span>
        </div>
        <div class="progress-bar">
            <div class="progress-fill" style="width: {percentage}%">{percentage:.1f}%</div>
        </div>
        """
    return html


def _generate_priority_chart(priorities: Dict[str, int]) -> str:
    """Generate HTML for priority distribution chart."""
    if not priorities:
        return "<p style='color: #999;'>No data available</p>"

    total = sum(priorities.values())
    html = ""
    for priority in ["P1", "P2", "P3"]:
        count = priorities.get(priority, 0)
        percentage = (count / total * 100) if total > 0 else 0
        html += f"""
        <div class="metric">
            <span class="metric-label">Priority {priority}</span>
            <span class="metric-value">{count}</span>
        </div>
        <div class="progress-bar">
            <div class="progress-fill" style="width: {percentage}%">{percentage:.1f}%</div>
        </div>
        """
    return html


def _generate_flaky_tests_table(flaky_tests: list) -> str:
    """Generate HTML table for flaky tests."""
    if not flaky_tests:
        return "<p style='color: #999;'>No flaky tests detected</p>"

    html = """
    <table>
        <thead>
            <tr>
                <th>Test ID</th>
                <th>Total Runs</th>
                <th>Passed</th>
                <th>Failed</th>
                <th>Flakiness Rate</th>
            </tr>
        </thead>
        <tbody>
    """

    for test in flaky_tests[:10]:  # Show top 10
        html += f"""
            <tr>
                <td>{test.get('test_id', 'N/A')}</td>
                <td>{test.get('total_runs', 0)}</td>
                <td>{test.get('pass_count', 0)}</td>
                <td>{test.get('fail_count', 0)}</td>
                <td><span class="status-badge status-flaky">{test.get('flakiness_rate', 0):.1f}%</span></td>
            </tr>
        """

    html += """
        </tbody>
    </table>
    """
    return html


if __name__ == "__main__":
    output = generate_html_dashboard()
    print(f"Dashboard generated: {output}")

