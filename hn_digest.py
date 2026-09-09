#!/usr/bin/env python3
"""Weekly Hacker News digest: fetches 850+ point stories, summarises via
Cloudflare Workers AI, and emails the digest."""

import argparse
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HN_ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
CF_AI_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"


def env(key, default=None):
    val = os.environ.get(key, default)
    if val is None:
        sys.exit(f"Error: missing required env var {key}")
    return val


# ---------------------------------------------------------------------------
# 1. Fetch high-scoring HN stories
# ---------------------------------------------------------------------------


def fetch_stories(min_score=850, days=7):
    """Return stories with >= min_score points from the last `days` days."""
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    stories = []
    page = 0

    while True:
        resp = requests.get(
            HN_ALGOLIA_URL,
            params={
                "tags": "story",
                "numericFilters": f"points>={min_score},created_at_i>={since}",
                "hitsPerPage": 50,
                "page": page,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        if not hits:
            break
        stories.extend(hits)
        if page >= data.get("nbPages", 1) - 1:
            break
        page += 1

    stories.sort(key=lambda s: s.get("points", 0), reverse=True)
    return stories


# ---------------------------------------------------------------------------
# 2. Extract article text
# ---------------------------------------------------------------------------


def extract_article_text(url, max_chars=3000):
    """Download and extract the main article text. Returns empty string on failure."""
    if not url:
        return ""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "hn-sum/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove scripts, styles, navs
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        return text[:max_chars]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 3. Summarise via Cloudflare Workers AI
# ---------------------------------------------------------------------------


def summarise(text, title, account_id, api_token):
    """Summarise article text using Cloudflare Workers AI (Llama 3.1 8B)."""
    if not text.strip():
        return "No article text available to summarise."

    url = CF_AI_URL.format(account_id=account_id)
    prompt = (
        f"Summarise this article in 2-3 concise sentences. "
        f"Article title: {title}\n\n{text}"
    )

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        json={
            "messages": [
                {"role": "system", "content": "You are a concise summariser. Respond with only the summary, no preamble."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 256,
        },
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    return result.get("result", {}).get("response", "Summary unavailable.")


# ---------------------------------------------------------------------------
# 4. Build email
# ---------------------------------------------------------------------------


def build_email_html(stories_with_summaries):
    """Build an HTML email body from the list of (story, summary) tuples."""
    now = datetime.now(timezone.utc).strftime("%d %B %Y")
    rows = []
    for story, summary in stories_with_summaries:
        title = story.get("title", "Untitled")
        url = story.get("url") or f"https://news.ycombinator.com/item?id={story['objectID']}"
        hn_url = f"https://news.ycombinator.com/item?id={story['objectID']}"
        points = story.get("points", 0)
        comments = story.get("num_comments", 0)

        rows.append(f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #eee;">
            <a href="{url}" style="font-size:16px;color:#1a1a1a;text-decoration:none;font-weight:600;">{title}</a>
            <br/>
            <span style="font-size:13px;color:#666;">{points} points &middot; {comments} comments &middot;
              <a href="{hn_url}" style="color:#ff6600;text-decoration:none;">HN thread</a>
            </span>
            <p style="margin:6px 0 0;font-size:14px;color:#333;line-height:1.5;">{summary}</p>
          </td>
        </tr>""")

    if not rows:
        rows.append("""
        <tr><td style="padding:24px;text-align:center;color:#666;">
          No stories hit the threshold this week.
        </td></tr>""")

    return f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px;">
      <h2 style="color:#ff6600;">Hacker News Weekly Digest</h2>
      <p style="color:#666;font-size:14px;">Week ending {now} &middot; Stories with 850+ points</p>
      <table style="width:100%;border-collapse:collapse;">
        {"".join(rows)}
      </table>
      <p style="margin-top:24px;font-size:12px;color:#999;">Generated by hn-sum</p>
    </body></html>"""


def send_email(html_body, gmail_address, gmail_app_password, to_address):
    """Send the digest email via Gmail SMTP."""
    now = datetime.now(timezone.utc).strftime("%d %b %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"HN Weekly Digest - {now}"
    msg["From"] = gmail_address
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_address, gmail_app_password)
        server.sendmail(gmail_address, to_address, msg.as_string())


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="HN weekly digest")
    parser.add_argument("--min-score", type=int, default=int(os.environ.get("HN_MIN_SCORE", "850")))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true", help="Print email HTML to stdout instead of sending")
    args = parser.parse_args()

    cf_account_id = env("CF_ACCOUNT_ID")
    cf_api_token = env("CF_API_TOKEN")

    print(f"Fetching HN stories with >= {args.min_score} points from the last {args.days} days...")
    stories = fetch_stories(min_score=args.min_score, days=args.days)
    print(f"Found {len(stories)} stories.")

    results = []
    for i, story in enumerate(stories):
        title = story.get("title", "Untitled")
        url = story.get("url", "")
        print(f"  [{i+1}/{len(stories)}] {title}")

        text = extract_article_text(url)
        summary = summarise(text, title, cf_account_id, cf_api_token)
        results.append((story, summary))

        # Be polite to Cloudflare free tier rate limits
        if i < len(stories) - 1:
            time.sleep(1)

    html = build_email_html(results)

    if args.dry_run:
        print("\n--- DRY RUN: Email HTML ---")
        print(html)
        return

    gmail_address = env("GMAIL_ADDRESS")
    gmail_app_password = env("GMAIL_APP_PASSWORD")
    to_address = env("EMAIL_TO")

    print(f"Sending digest to {to_address}...")
    send_email(html, gmail_address, gmail_app_password, to_address)
    print("Done!")


if __name__ == "__main__":
    main()
