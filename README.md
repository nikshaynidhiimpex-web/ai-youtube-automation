# AI Hindi YouTube Shorts Automation

Roz ek Hindi facts Short apne aap banata hai, best time par publish karta hai,
aur pichhli videos ke analytics se seekh kar agli video behtar banata hai.

## Har run mein kya hota hai

1. **Analytics**: pichhli videos ke views, likes, comments (YouTube Data API)
   aur retention, shares, subscribers (YouTube Analytics API) laata hai, aur
   har video ke 24 ghante ke views nikalta hai. Ye sab `data/history.json` mein save hota hai.
2. **Script**: Gemini ko best aur kamzor videos ka data diya jaata hai.
   Gemini 5-7 scenes ki script likhta hai aur pichhle topics repeat nahi karta.
3. **Voice**: Microsoft Edge neural Hindi voice (free). Fail ho to espeak-ng.
4. **Visuals**: har scene ke liye Pixabay/Pexels (agar key ho) se stock video
   ya photo, warna **Wikimedia Commons** se free photo (koi key nahi chahiye;
   photographer + license ka credit description mein apne aap judta hai).
   Kuch na mile to animated gradient background.
5. **Motion graphics (FFmpeg)**: photo par zoom/pan, scene flash transitions,
   karaoke subtitles (bole gaye shabd peele hote hain), animated caption cards,
   red hook card, progress bar, Subscribe CTA, aur -14 LUFS audio.
   `assets/music/` mein royalty-free mp3 daaloge to background music bhi lagega.
6. **Publish time**: roz alag time. Pehle har slot try karta hai, phir zyada
   tar best slot use karta hai, kabhi-kabhi naya slot bhi. YouTube par
   "scheduled" upload hota hai, us time apne aap public ho jaata hai.

## GitHub settings

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

| Name | Kya hai |
|---|---|
| `GEMINI_API_KEY` | Google AI Studio key |
| `YOUTUBE_TOKEN_JSON` | `python get_token.py` ka output |
| `YOUTUBE_EXPECTED_CHANNEL_NAME` | Channel ka exact naam |
| `PIXABAY_API_KEY` | Free key: pixabay.com par login → https://pixabay.com/api/docs/ (recommended) |
| `PEXELS_API_KEY` | Optional. Pexels ne naye keys abhi band kiye hain |

**Variables** (optional):

| Name | Default |
|---|---|
| `GEMINI_MODEL` | list ka pehla model |
| `TTS_VOICE` | `hi-IN-MadhurNeural` (female: `hi-IN-SwaraNeural`) |
| `PUBLISH_SLOTS_IST` | `9,11,13,15,17,18,19,20,21` (IST hours) |

## YouTube token (sirf ek baar)

1. Google Cloud Console → APIs: **YouTube Data API v3** aur
   **YouTube Analytics API** dono enable karo.
2. OAuth consent screen → **Publish app** ("In production" status).
   Testing mode mein token har 7 din mein expire hota hai; production mein nahi.
   Login ke time "Google hasn't verified this app" aaye to
   Advanced → Go to app (unsafe) dabao. Ye tumhara apna app hai.
3. OAuth Client (Desktop app) ka JSON `client_secret.json` naam se is folder mein rakho.
4. `pip install google-auth-oauthlib` → `python get_token.py`
5. Print hua JSON `YOUTUBE_TOKEN_JSON` secret mein paste karo.

## Chalana

- **Automatic**: roz 06:00 IST par banti hai aur best time par **public** hoti hai.
- **Test**: Actions → Daily Hindi YouTube Short → Run workflow → privacy `private`.
  Bani hui video run ke "Artifacts" mein 7 din tak download ki ja sakti hai.
- Ek din mein ek hi public video banti hai. Dobara chahiye to `force` tick karo.

## Local test (bina upload)

```bash
DRY_RUN=1 GEMINI_API_KEY=... python main.py
```
