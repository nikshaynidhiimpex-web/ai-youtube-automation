# Daily Hindi YouTube Short — zero-subscription starter

This is a starter workflow, not a guaranteed unlimited free service. It runs on
GitHub Actions, asks Gemini for a Hindi script, uses espeak-ng for a basic Hindi
voice, renders a simple vertical motion-card video with FFmpeg, and uploads it
to YouTube. The first uploads are private by default.

## Important limitations

- GitHub Actions free minutes and storage are limited. Public standard runners
  are generally free; private repositories use the account's included quota.
- Gemini free-tier availability, model names, rate limits and terms can change.
- `espeak-ng` Hindi voice is robotic. It is a no-cost proof-of-concept, not a
  polished AI narrator.
- The video uses a simple generated background and text, not stock footage.
  This is intentional: do not scrape other creators' videos or reuse copyrighted
  music/clips.
- This script is a prototype. Review facts, script, pronunciation, thumbnail,
  rights and YouTube policy before publishing.
- OAuth consent in Testing causes YouTube-scope authorizations and refresh
  tokens to expire after 7 days; see the OAuth note below.
- Do not make public auto-publishing the default until the workflow is tested.

## 1. Create a GitHub repository

Create a repository. For a zero-cost prototype, make it **public** (do not put
secrets or personal data in the repository). Upload these files.

## 2. Get a Gemini API key

Create a key in Google AI Studio. Add it to GitHub:
Settings → Secrets and variables → Actions → New repository secret
Name: `GEMINI_API_KEY`

## 3. Configure YouTube OAuth

In Google Cloud Console:
1. Create/select a project.
2. Enable YouTube Data API v3.
3. Configure the OAuth consent screen. For a personal one-channel setup,
   choose External if you use a personal Google account.
4. Create an OAuth Client ID of type Desktop app.
5. If the app is in Testing, add your Google account as a test user.
   Important: Google's Testing publishing status causes authorizations and their
   refresh tokens to expire after 7 days for YouTube upload scope. For daily
   unattended use, you will need to understand the OAuth publishing-status
   requirements and move out of Testing where appropriate. Personal-use apps
   may qualify for an exception from verification, but Google may still show
   an unverified-app warning.
6. Download the OAuth client JSON as `client_secret.json`.

On your own computer (one-time setup only), install:
`pip install google-auth-oauthlib`

Run this Python snippet in the folder containing `client_secret.json`:

```python
from google_auth_oauthlib.flow import InstalledAppFlow
import json
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print(creds.to_json())
```

Copy the complete JSON printed by the script. In GitHub repository:
Settings → Secrets and variables → Actions → New repository secret
Name: `YOUTUBE_TOKEN_JSON`
Value: paste the complete JSON.

Never commit either JSON file or expose these secrets in logs.

## 4. Run a private test

Repository → Settings → Secrets and variables → Actions:
Add `GEMINI_API_KEY` and `YOUTUBE_TOKEN_JSON`.

Actions tab → Daily Hindi YouTube Short → Run workflow.
The default privacy status is `private`.

If successful, inspect the uploaded private video in YouTube Studio. If the
workflow fails, open its log and diagnose the failing step. Never paste API
keys or OAuth tokens into chat.

## 5. Schedule

The workflow runs daily at 09:00 UTC (14:30 India time). GitHub scheduled
workflows can be delayed and may be disabled for inactive public repositories.
Change the cron line in `.github/workflows/daily-short.yml` if needed.

## 6. Optional settings

Repository → Settings → Secrets and variables → Actions → Variables:
- `YOUTUBE_PRIVACY_STATUS`: keep `private` while testing; change to `unlisted`
  or `public` only after you have reviewed policy and API restrictions.
- `GEMINI_MODEL`: set to a currently available model in your AI Studio account.

## Notes on improving quality

This first prototype creates a simple text-card Short with Hindi narration.
Next iterations can add:
- licensed/public-domain images or user-owned visuals,
- Hindi subtitle timing,
- proper thumbnail typography with a Devanagari font,
- script fact-checking against reliable sources,
- manual approval before publishing,
- analytics and duplicate-topic prevention.

## Current API notes (check before deployment)

- The default model in this starter is `gemini-3.8-flash`; model access and free
  quotas vary by account and can change. Check Google's current model and pricing
  pages before running.
- YouTube upload uses OAuth 2.0; API keys alone cannot upload.
- The YouTube Data API currently documents `videos.insert` as 1 unit in the
  video-upload quota bucket and supports metadata with the upload.
- As of the YouTube Data API revision dated November 2, 2026, the earlier rule
  forcing unverified API-project uploads to private was reversed. Still start
  with private uploads and inspect the result before changing visibility.
