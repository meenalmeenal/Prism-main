import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Execution Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        .dashboard { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .metrics { display: flex; justify-content: space-between; margin: 20px 0; }
        .metric-card { 
            background: #f5f5f5; 
            padding: 15px; 
            border-radius: 5px; 
            width: 23%; 
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .test-table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .test-table th, .test-table td { 
            border: 1px solid #ddd; 
            padding: 8px; 
            text-align: left; 
        }
        .test-table tr:nth-child(even) { background-color: #f2f2f2; }
        .test-table th { 
            background-color: #4CAF50; 
            color: white; 
        }
        .pass { color: green; }
        .fail { color: red; }
    </style>
</head>
<body>
    <div class="dashboard">
        <h1>Test Execution Dashboard</h1>
        <p>Generated on: {generation_time}</p>
        
        <div class="metrics">
            <div class="metric-card">
                <h3>Test Coverage</h3>
                <div class="metric-value">{test_coverage}%</div>
                <div class="metric-chart">
                    <canvas id="coverageChart" width="200" height="200"></canvas>
                </div>
            </div>
            <div class="metric-card">
                <h3>Passed Tests</h3>
                <div class="metric-value">{passed_tests}</div>
            </div>
            <div class="metric-card">
                <h3>Failed Tests</h3>
                <div class="metric-value">{failed_tests}</div>
            </div>
            <div class="metric-card">
                <h3>Total Tests</h3>
                <div class="metric-value">{total_tests}</div>
            </div>
        </div>
        
        <h2>Test Execution Results</h2>
        <table class="test-table">
            <thead>
                <tr>
                    <th>Test Case</th>
                    <th>Status</th>
                    <th>Jira ID</th>
                    <th>Duration (s)</th>
                </tr>
            </thead>
            <tbody>
                {test_rows}
            </tbody>
        </table>
    </div>

    <script>
        // Charts initialization
        const coverageCtx = document.getElementById('coverageChart').getContext('2d');
        new Chart(coverageCtx, {{
            type: 'doughnut',
            data: {{
                labels: ['Passed', 'Failed'],
                datasets: [{{
                    data: [{passed_tests}, {failed_tests}],
                    backgroundColor: ['#4CAF50', '#f44336']
                }}]
            }}
        }});
    </script>
</body>
</html>
"""

class DashboardGenerator:
    def __init__(self, results_path: str = "execution_results.json"):
        self.results_path = Path(results_path)
        self.output_dir = Path("reports")
        self.output_dir.mkdir(exist_ok=True)

    def generate(self) -> str:
        """Generate and save the dashboard HTML."""
        if not self.results_path.exists():
            raise FileNotFoundError(f"Results file not found: {self.results_path}")

        with open(self.results_path) as f:
            results = json.load(f)

        # Calculate metrics
        test_cases = results.get("test_cases", [])
        total_tests = len(test_cases)
        passed_tests = sum(1 for tc in test_cases if tc.get("status") == "PASS")
        failed_tests = total_tests - passed_tests
        test_coverage = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        # Generate test rows
        test_rows = []
        for test in test_cases:
            status_class = "pass" if test.get("status") == "PASS" else "fail"
            test_rows.append(f"""
                <tr>
                    <td>{test.get('name', 'Unnamed Test')}</td>
                    <td class="{status_class}">{test.get('status', 'UNKNOWN')}</td>
                    <td>{test.get('jira_id', 'N/A')}</td>
                    <td>{test.get('duration', 0):.2f}</td>
                </tr>
            """)

        # Render template
        dashboard_html = DASHBOARD_TEMPLATE.format(
            generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            test_coverage=f"{test_coverage:.1f}",
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            total_tests=total_tests,
            test_rows="\n".join(test_rows)
        )

        # Save the dashboard
        output_path = self.output_dir / "dashboard.html"
        output_path.write_text(dashboard_html)
        logger.info(f"Generated dashboard at {output_path}")
        return str(output_path)
