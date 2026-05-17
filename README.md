# Social Media Agent

Automate social media posting for your clothes reselling business. Scrapes your Depop shop listings and creates posts for Pinterest and Instagram to drive traffic.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Copy and fill in your API keys
cp .env.example .env

# First-time setup: solve Cloudflare challenge
python main.py setup --shop YOUR_DEPOP_USERNAME

# Scrape your listings
python main.py scrape --shop YOUR_DEPOP_USERNAME

# Generate captions (uses Claude AI)
python main.py generate --platform pinterest

# Review and approve posts
python main.py review

# Publish approved posts
python main.py publish --platform pinterest
```

## Commands

| Command | Description |
|---------|-------------|
| `setup` | One-time browser setup to pass Cloudflare (saves cookies) |
| `scrape` | Fetch listings from your Depop shop |
| `generate` | Generate AI captions for new listings |
| `review` | Approve/reject/edit draft posts |
| `publish` | Publish approved posts to Pinterest/Instagram |
| `status` | Show queue statistics |
| `auth pinterest` | Run Pinterest OAuth flow |
| `auth instagram` | Show Instagram Business account setup guide |

## Setup

### Required: Anthropic API Key
Get one at https://console.anthropic.com — used for AI caption generation.

### Pinterest
1. Create an app at https://developers.pinterest.com/apps/
2. Run `python main.py auth pinterest` to complete OAuth
3. Choose which board to post to

### Instagram (coming soon)
Requires a Business account connected to a Facebook Page. Run `python main.py auth instagram` for full setup guide.

## How It Works

1. **Scrape** — Fetches your active Depop listings (title, description, price, images)
2. **Generate** — Creates engaging, platform-specific captions using Claude AI
3. **Review** — Queue system lets you approve, edit, or reject posts before publishing
4. **Publish** — Posts approved content to Pinterest/Instagram with links back to your listings

## Notes

- First scrape requires solving a Cloudflare challenge in the browser (run `setup` once)
- Subsequent scrapes reuse saved cookies automatically
- AI captions fall back to listing text if no API key is set
- Pinterest has a 25-pin/day soft limit; Instagram has a hard 25-post/day limit
