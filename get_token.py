"""One-time helper: create YOUTUBE_TOKEN_JSON on your own computer.

1. Google Cloud Console se OAuth "Desktop app" client JSON download karke
   is folder mein `client_secret.json` naam se rakho.
2. pip install google-auth-oauthlib
3. python get_token.py
4. Browser mein apne channel wale Google account se login karke Allow karo.
5. Jo JSON print ho, use GitHub secret YOUTUBE_TOKEN_JSON mein paste karo.

client_secret.json aur token kabhi commit mat karna (.gitignore mein hai).
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\n===== COPY EVERYTHING BELOW INTO GitHub secret YOUTUBE_TOKEN_JSON =====\n")
print(creds.to_json())
