# hn-sum

Weekly Hacker News digest - fetches stories with 850+ points, summarises them
via Cloudflare Workers AI (Llama 3.1 8B, free tier), and emails the digest.

Runs automatically every Monday at 9am UTC via GitHub Actions.

## Setup

### 1. Gmail App Password

- Enable 2FA on your Google account
- Go to https://myaccount.google.com/apppasswords
- Generate an app password for "Mail"

### 2. Cloudflare API Token

- Go to https://dash.cloudflare.com/profile/api-tokens
- Create a token with **Workers AI - Read** permission
- Note your Account ID from the dashboard URL or overview page

### 3. GitHub Secrets

Add these secrets in your repo under Settings > Secrets > Actions:

| Secret | Description |
|--------|-------------|
| `CF_ACCOUNT_ID` | Cloudflare account ID |
| `CF_API_TOKEN` | Cloudflare API token |
| `GMAIL_ADDRESS` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail app password (not your real password) |
| `EMAIL_TO` | Recipient email address |

### 4. Run manually

Trigger from the Actions tab using "Run workflow", or locally:

```bash
cp .env.example .env
# fill in .env values
export $(cat .env | xargs)
pip install -r requirements.txt
python hn_digest.py --dry-run
```

## Options

```
--min-score N   Minimum points threshold (default: 850)
--days N        Look back N days (default: 7)
--dry-run       Print HTML to stdout instead of sending email
```
