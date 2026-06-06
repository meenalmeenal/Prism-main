"""
Jira connection diagnostic script - Enhanced.
Run with: python diagnose_jira.py
"""
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Find and show which .env file is being loaded
env_path = find_dotenv(usecwd=True)
print("=" * 60)
print("ENV FILE DIAGNOSTICS")
print("=" * 60)
print(f"Python executable : {sys.executable}")
print(f"Working directory : {os.getcwd()}")
print(f".env file found at: {env_path or 'NOT FOUND'}")
print()

# Load it
load_dotenv(env_path, override=True)

base_url = os.getenv("JIRA_BASE_URL", "")
email    = os.getenv("JIRA_EMAIL", "")
token    = os.getenv("JIRA_API_TOKEN", "")

# Strip any hidden whitespace
base_url_clean = base_url.strip().rstrip("/")
email_clean    = email.strip()
token_clean    = token.strip()

print("RAW VALUES FROM .env:")
print(f"  JIRA_BASE_URL  : '{base_url}' (len={len(base_url)})")
print(f"  JIRA_EMAIL     : '{email}' (len={len(email)})")
print(f"  JIRA_API_TOKEN : first='{token[:10]}' last='{token[-10:]}' len={len(token)}")
print()
print("AFTER STRIPPING WHITESPACE:")
print(f"  base_url  changed: {base_url != base_url_clean} → '{base_url_clean}'")
print(f"  email     changed: {email != email_clean} → '{email_clean}'")
print(f"  token     changed: {token != token_clean} → first='{token_clean[:10]}' last='{token_clean[-10:]}'")
print()

# Show raw .env file content for the token line
if env_path:
    print("RAW .env FILE (token line only):")
    with open(env_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if "JIRA_API_TOKEN" in line:
                print(f"  Line {i}: {repr(line)}")
    print()

if not base_url_clean or not email_clean or not token_clean:
    print("❌ ERROR: One or more env vars are EMPTY. Check your .env file.")
    sys.exit(1)

print("=" * 60)
print("JIRA API TESTS")
print("=" * 60)

auth    = (email_clean, token_clean)
headers = {"Accept": "application/json"}

# Test 1: /myself
print("TEST 1: GET /rest/api/3/myself")
url = f"{base_url_clean}/rest/api/3/myself"
print(f"  URL: {url}")
try:
    r = requests.get(url, headers=headers, auth=auth, timeout=10)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  ✅ Authenticated as: {data.get('displayName')} <{data.get('emailAddress')}>")
    elif r.status_code == 401:
        print(f"  ❌ 401 — token/email mismatch")
        print(f"  Response: {r.text[:400]}")
    else:
        print(f"  ❌ {r.status_code}: {r.text[:400]}")
except Exception as e:
    print(f"  ❌ Exception: {e}")

print()
print("=" * 60)
print("Done. Share this full output.")
