import asyncio
import hashlib
import hmac
import json
import logging
import os
from aiohttp import web
from dotenv import load_dotenv
from src.reporting.run_summary import generate_and_open_summary
# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

# Configure logging to console and a file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/webhook_listener.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("WebhookListener")

load_dotenv(override=True)

from src.pipeline.enhanced_pipeline import run_enhanced_pipeline_async

# Setup configuration
PORT = int(os.getenv("WEBHOOK_PORT", "5000"))
JIRA_SECRET = os.getenv("JIRA_WEBHOOK_SECRET", "")
GITHUB_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")

async def run_pipeline_in_background(source: str, identifier: str):
    """Safely run the enhanced pipeline in the background and log results."""
    logger.info(f"Starting background pipeline run for source='{source}', identifier='{identifier}'")
    try:
        result = await run_enhanced_pipeline_async(
            source=source,
            identifier=identifier,
            dry_run=os.getenv("ZEPHYR_DRY_RUN", "false").lower() in {"1", "true", "yes"}
        )
        logger.info(f"Background pipeline run completed for {identifier}. Result: {result.get('issue_key') or 'Batch completed'}")
        try:
            path = generate_and_open_summary(result)
            logger.info(f"Run summary written and opened: {path}")
        except Exception as e:
            logger.warning(f"Could not generate/open run summary: {e}")
    except Exception as e:
        logger.exception(f"Error executing background pipeline for {identifier}: {e}")
        
async def jira_webhook_handler(request: web.Request) -> web.Response:
    logger.info("Received Jira Webhook request.")

    if JIRA_SECRET:
        token = request.query.get("secret")
        if not token or not hmac.compare_digest(token, JIRA_SECRET):
            logger.warning("Jira Webhook unauthorized: Invalid secret token.")
            return web.Response(text="Unauthorized: Invalid secret token", status=401)

    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body from Jira Webhook: {e}")
        return web.Response(text="Invalid JSON payload", status=400)

    event = payload.get("webhookEvent")
    issue = payload.get("issue", {})
    issue_key = issue.get("key")
    fields = issue.get("fields", {})
    issue_type = fields.get("issuetype", {}).get("name", "")

    logger.info(f"Jira Webhook Event: {event} | Issue Key: {issue_key} | Issue Type: {issue_type}")

    if not issue_key:
        logger.warning("Jira Webhook received but no valid issue key found in payload.")
        return web.Response(text="No valid issue key found in payload", status=200)

    should_run = False

    if event == "jira:issue_updated":
        changelog_items = payload.get("changelog", {}).get("items", [])
        changed_fields = {item.get("field") for item in changelog_items}
        if "description" in changed_fields:
            should_run = True
        else:
            logger.info(f"Ignoring update to {issue_key} — changed fields: {changed_fields}")

    elif event == "jira:issue_created":
        labels = fields.get("labels", []) or []
        if "auto-created-from-pr" in labels:
            logger.info(f"Ignoring creation of {issue_key} — auto-created from a GitHub PR, pipeline already ran.")
        else:
            # Only run immediately on creation if description was already filled in at create time
            description = fields.get("description")
            if description:
                should_run = True
            else:
                logger.info(f"Ignoring creation of {issue_key} — description empty, will wait for update.")

    if should_run:
        logger.info(f"Triggering background pipeline for Jira issue {issue_key}")
        asyncio.create_task(run_pipeline_in_background(source="jira", identifier=issue_key))
        return web.Response(text=f"Pipeline triggered for Jira issue {issue_key}", status=200)

    return web.Response(text=f"Event ignored for {issue_key}", status=200)

async def github_webhook_handler(request: web.Request) -> web.Response:
    """Handle incoming GitHub Webhooks (Pull Requests)."""
    logger.info("Received GitHub Webhook request.")
    
    # 1. Verify HMAC SHA256 signature if configured
    if GITHUB_SECRET:
        signature = request.headers.get("X-Hub-Signature-256")
        if not signature:
            logger.warning("GitHub Webhook unauthorized: Missing X-Hub-Signature-256 header.")
            return web.Response(text="Unauthorized: Missing signature header", status=401)
            
        body = await request.read()
        expected = "sha256=" + hmac.new(
            GITHUB_SECRET.encode("utf-8"),
            body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected):
            logger.warning("GitHub Webhook unauthorized: Invalid signature.")
            return web.Response(text="Unauthorized: Signature verification failed", status=401)

    # 2. Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body from GitHub Webhook: {e}")
        return web.Response(text="Invalid JSON payload", status=400)

    # 3. Check event type and pull request status
    event_type = request.headers.get("X-GitHub-Event")
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    pr_url = pr.get("html_url")

    logger.info(f"GitHub Webhook Event: {event_type} | Action: {action} | PR URL: {pr_url}")

    if event_type == "pull_request" and pr_url:
        # Trigger on PR opened, reopened, synchronized (new push), edited, or ready for review
        if action in {"opened", "reopened", "synchronize", "edited", "ready_for_review"}:
            logger.info(f"Triggering background pipeline for GitHub PR {pr_url} (action={action})")
            asyncio.create_task(run_pipeline_in_background(source="github_pr", identifier=pr_url))
            return web.Response(text=f"Pipeline triggered for GitHub PR {pr_url}", status=200)
        else:
            logger.info(f"Ignoring GitHub PR action '{action}'")
            return web.Response(text=f"Ignoring action '{action}'", status=200)

    logger.warning("GitHub Webhook received but not a relevant pull request event.")
    return web.Response(text="Not a pull_request event, ignoring", status=200)

async def health_handler(request: web.Request) -> web.Response:
    """Simple health check endpoint."""
    return web.Response(text="Webhook listener is healthy", status=200)

async def _run_app():
    """Async entry point using AppRunner for Python 3.13 compatibility."""
    app = web.Application()
    app.router.add_post("/webhook/jira", jira_webhook_handler)
    app.router.add_post("/webhook/github", github_webhook_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logger.info(f"======== Running on http://0.0.0.0:{PORT} ========")
    logger.info("(Press CTRL+C to quit)")
    try:
        await asyncio.Event().wait()  # run forever until Ctrl+C
    finally:
        await runner.cleanup()


def main():
    logger.info(f"Starting Webhook Listener on port {PORT}...")
    if JIRA_SECRET:
        logger.info("Jira Webhook secret token verification is enabled.")
    else:
        logger.info("Jira Webhook secret token verification is disabled (JIRA_WEBHOOK_SECRET not set).")

    if GITHUB_SECRET:
        logger.info("GitHub Webhook HMAC signature verification is enabled.")
    else:
        logger.info("GitHub Webhook HMAC signature verification is disabled (GITHUB_WEBHOOK_SECRET not set).")

    try:
        asyncio.run(_run_app())
    except (KeyboardInterrupt, IndexError):
        logger.info("Webhook Listener stopped.")


if __name__ == "__main__":
    main()
