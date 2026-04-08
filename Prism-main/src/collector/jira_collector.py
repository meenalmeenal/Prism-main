# src/collector/jira_collector.py
import os
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv


# Create logs directory FIRST
Path("logs").mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/jira_collector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class JiraCollector:
    """Fetches issues and acceptance criteria from Jira"""
    
    def __init__(self):
        self.base_url = os.getenv("JIRA_BASE_URL")
        self.email = os.getenv("JIRA_EMAIL")
        self.api_token = os.getenv("JIRA_API_TOKEN")
        
        if not all([self.base_url, self.email, self.api_token]):
            raise ValueError("Missing Jira credentials in .env file")
        
        self.auth = HTTPBasicAuth(self.email, self.api_token)
        self.headers = {"Accept": "application/json"}
        logger.info("JiraCollector initialized successfully")
        
    def fetch_issue(self, issue_key: str) -> Dict:
        """Fetch a single Jira issue by key"""
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        
        try:
            logger.info(f"Fetching issue: {issue_key}")
            response = requests.get(
                url, 
                headers=self.headers, 
                auth=self.auth, 
                timeout=30
            )
            response.raise_for_status()
            
            issue_data = response.json()
            logger.info(f"Successfully fetched {issue_key}")
            return issue_data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.error(f"Issue {issue_key} not found")
            else:
                logger.error(f"HTTP error: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {issue_key}: {e}")
            raise
    
    def fetch_issues_by_jql(self, jql: str, max_results: int = 100) -> List[Dict]:
        """Fetch multiple issues using JQL query"""
        url = f"{self.base_url}/rest/api/3/search"
        
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,description,issuetype,status,priority,reporter,assignee"
        }
        
        try:
            logger.info(f"Executing JQL: {jql}")
            response = requests.get(
                url,
                headers=self.headers,
                auth=self.auth,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            issues = data.get("issues", [])
            logger.info(f"Found {len(issues)} issues")
            return issues
            
        except requests.exceptions.RequestException as e:
            logger.error(f"JQL query failed: {e}")
            raise
    
    def extract_acceptance_criteria(self, issue_data: Dict) -> List[str]:
        """Extract acceptance criteria from issue description"""
        fields = issue_data.get("fields", {})
        description = fields.get("description", {})
        
        # Extract text from Atlassian document format
        text = self._extract_text_from_description(description)
        
        if not text:
            logger.warning("No description found")
            return []
        
        # Find acceptance criteria section
        acs = []
        lines = text.split('\n')
        in_ac_section = False
        
        for line in lines:
            line = line.strip()
            
            # Check if we've reached AC section
            if "acceptance criteria" in line.lower():
                in_ac_section = True
                continue
            
            # Extract numbered criteria
            if in_ac_section and line:
                # Remove numbering (1., 2., etc.)
                cleaned = line.lstrip('0123456789.)-* ').strip()
                if cleaned and len(cleaned) > 10:  # Avoid empty/short lines
                    acs.append(cleaned)
        
        logger.info(f"Extracted {len(acs)} acceptance criteria")
        return acs
    
    def _extract_text_from_description(self, description) -> str:
        """Extract plain text from Jira's document format"""
        if isinstance(description, str):
            return description
        
        if not isinstance(description, dict):
            return ""
        
        texts = []
        
        def walk(node):
            if isinstance(node, dict):
                if "text" in node:
                    texts.append(node["text"])
                for child in node.get("content", []):
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
        
        walk(description)
        return '\n'.join(texts)
    
    def save_issue_data(self, issue_key: str, issue_data: Dict, output_dir: str = "data"):
        """Save issue data to JSON file"""
        Path(output_dir).mkdir(exist_ok=True)
        
        output_path = Path(output_dir) / f"{issue_key}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(issue_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved issue data to {output_path}")
        return output_path
    
    def get_issue_summary(self, issue_data: Dict) -> Dict:
        """Extract key fields from issue"""
        fields = issue_data.get("fields", {})
        
        return {
            "key": issue_data.get("key"),
            "summary": fields.get("summary", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "status": fields.get("status", {}).get("name", ""),
            "priority": fields.get("priority", {}).get("name", ""),
            "reporter": fields.get("reporter", {}).get("displayName", ""),
            "assignee": fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned",
            "acceptance_criteria": self.extract_acceptance_criteria(issue_data)
        }


def main():
    """Test the collector"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python jira_collector.py <ISSUE_KEY>")
        print("   or: python jira_collector.py --jql 'project=ZT AND sprint=\"ZT Sprint 1\"'")
        print("\nExample: python jira_collector.py ZT-3")
        sys.exit(1)
        
    collector = JiraCollector()
    
    if sys.argv[1] == "--jql":
        jql = sys.argv[2]
        issues = collector.fetch_issues_by_jql(jql)
        
        print(f"\n{'='*60}")
        print(f"Found {len(issues)} issues")
        print('='*60)
        
        for issue in issues:
            summary = collector.get_issue_summary(issue)
            print(f"\n📌 {summary['key']}: {summary['summary']}")
            print(f"   Status: {summary['status']}")
            print(f"   ACs: {len(summary['acceptance_criteria'])}")
    else:
        issue_key = sys.argv[1]
        issue_data = collector.fetch_issue(issue_key)
        collector.save_issue_data(issue_key, issue_data)
        
        summary = collector.get_issue_summary(issue_data)
        
        print(f"\n{'='*60}")
        print(f"✅ Issue: {summary['key']}")
        print('='*60)
        print(f"📝 Summary: {summary['summary']}")
        print(f"📊 Status: {summary['status']}")
        print(f"🎯 Type: {summary['issue_type']}")
        print(f"⭐ Priority: {summary['priority']}")
        print(f"👤 Reporter: {summary['reporter']}")
        print(f"👨‍💻 Assignee: {summary['assignee']}")
        
        print(f"\n📋 Acceptance Criteria ({len(summary['acceptance_criteria'])}):")
        for i, ac in enumerate(summary['acceptance_criteria'], 1):
            print(f"  {i}. {ac}")


if __name__ == "__main__":
    main()