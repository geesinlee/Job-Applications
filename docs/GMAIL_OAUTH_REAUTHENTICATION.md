# Gmail OAuth Re-authentication Guide

## Problem

Gmail OAuth refresh token has expired. Service is failing with:
```
Token refresh failed: 400 Client Error: Bad Request
invalid_grant: Token has been expired or revoked
```

## Solution

Re-authenticate the `geesin@gmail.com` account to get a fresh OAuth token.

---

## Step-by-Step Instructions

### Step 1: Get OAuth Credentials from Google Cloud Console

You need the OAuth **client_id** and **client_secret** for the Job Applications app.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select the project with Gmail API enabled (likely "Job-Applications" or similar)
3. Go to **Credentials** (left sidebar)
4. Find the OAuth 2.0 Client ID for "Desktop application"
5. Copy the **Client ID** and **Client Secret** (keep safe, don't commit to git)

**If OAuth app doesn't exist:**
- Click **Create Credentials** → **OAuth client ID** → **Desktop app**
- Grant scopes: `https://www.googleapis.com/auth/gmail.modify`

---

### Step 2: Run Re-authentication Script (On Mac)

Create a script that opens the OAuth flow and saves the token.

```bash
# On Mac, in the Job-Applications directory
python3 << 'EOF'
import json
import sys
import webbrowser
from google.auth.oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# OAuth credentials from Google Cloud Console
CLIENT_ID = "YOUR_CLIENT_ID_HERE"
CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"

# Gmail API scope
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# OAuth flow
flow = InstalledAppFlow.from_client_secrets_dict(
    {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    scopes=SCOPES
)

print("Opening browser for Gmail authentication...")
print("Log in as: geesin@gmail.com")
print("")

creds = flow.run_local_server(port=8080, open_browser=True)

print("\n✅ Authentication successful!")
print(f"Access Token: {creds.token[:30]}...")
print(f"Refresh Token: {creds.refresh_token[:30]}...")

# Save credentials
creds_data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "refresh_token": creds.refresh_token,
    "type": "authorized_user"
}

with open("creds/geesin.json", "w") as f:
    json.dump(creds_data, f, indent=2)

print("\n✅ Saved to creds/geesin.json")
print("\nNext steps:")
print("1. Copy creds/geesin.json to pi-4")
print("2. Restart service on pi-4: systemctl --user restart job-applications-digest.service")

EOF
```

**Important:** Replace `YOUR_CLIENT_ID_HERE` and `YOUR_CLIENT_SECRET_HERE` with actual values from Google Cloud Console.

---

### Step 3: Automated Re-auth Script (Easier Method)

I've created a helper script. Run it:

```bash
cd /Users/gslee/Projects/Job-Applications
python3 gmail_oauth_reauthenticate.py
```

This script:
1. Reads OAuth credentials from environment or `.env`
2. Opens browser for you to log in as `geesin@gmail.com`
3. Gets new refresh token
4. Saves to `creds/geesin.json`
5. Prompts to copy to pi-4

---

### Step 4: Copy New Credentials to pi-4

Once you have the new `creds/geesin.json`:

```bash
scp /Users/gslee/Projects/Job-Applications/creds/geesin.json \
    gs@gs-pi-4:/home/gs/Projects/Job-Applications/creds/

echo "✅ Credentials copied to pi-4"
```

Verify it was copied:
```bash
ssh gs@gs-pi-4 "ls -la ~/Projects/Job-Applications/creds/"
```

---

### Step 5: Restart the Service on pi-4

```bash
ssh gs@gs-pi-4 <<'EOF'
systemctl --user daemon-reload
systemctl --user restart job-applications-digest.service

echo "✅ Service restarted"
sleep 2

# Check status
systemctl --user status job-applications-digest.service --no-pager | head -15
EOF
```

Expected output:
```
● job-applications-digest.service - Job Applications Daily Job Digest Run
     Loaded: loaded (/home/gs/.config/systemd/user/job-applications-digest.service; enabled; vendor preset: enabled)
     Active: inactive (dead)
```

---

### Step 6: Test the Service

```bash
# Run manually on pi-4
ssh gs@gs-pi-4 <<'EOF'
cd ~/Projects/Job-Applications
source venv/bin/activate
python3 job_digest.py
EOF
```

Expected output:
```
2026-08-20 XX:XX:XX,XXX [job_digest] INFO: === Job digest starting ===
2026-08-20 XX:XX:XX,XXX [gmail_auth] INFO: Successfully authenticated 'geesin'
2026-08-20 XX:XX:XX,XXX [job_digest] INFO: Processing account 'geesin'
...
✅ Job digest completed successfully
```

---

### Step 7: Verify Automatic Schedule

Timer should run tomorrow at 02:00 SGT:

```bash
ssh gs@gs-pi-4 "systemctl --user list-timers job-applications-digest.timer"
```

Expected:
```
NEXT                         LEFT     LAST                        PASSED  UNIT
...                          ...      Thu 2026-08-20 02:00:32 +08 9h ago  job-applications-digest.timer
```

---

## Troubleshooting

### Issue: "Port 8080 already in use"
```bash
# Use different port
python3 gmail_oauth_reauthenticate.py --port 8081
```

### Issue: "Browser didn't open"
Manually visit: `http://localhost:8080/` and complete the flow.

### Issue: "geesin@gmail.com not showing up"
Make sure you're using the right Google account. If you see a different account:
1. Log out in the browser
2. Try again

### Issue: "Still getting 'invalid_grant' error"
The token may have been revoked. Try:
```bash
# Clear old token and re-authenticate
rm creds/geesin.json
python3 gmail_oauth_reauthenticate.py
```

### Issue: Service still failing after restart
Check logs:
```bash
ssh gs@gs-pi-4 "journalctl --user -u job-applications-digest.service -n 20"
```

---

## What's Happening Behind the Scenes

1. **OAuth Flow:** Opens browser for user login
2. **Authorization:** Google asks permission to access Gmail
3. **Token Generation:** Google returns access + refresh tokens
4. **Storage:** Refresh token saved in `creds/geesin.json`
5. **Service Use:** `job_digest.py` uses refresh token to get access tokens

---

## Security Notes

⚠️ **DO NOT:**
- Commit `creds/geesin.json` to git
- Share tokens in chat or emails
- Store in version control

✅ **DO:**
- Keep `creds/geesin.json` secure (permissions 600)
- Store in password manager if needed for reference
- Rotate if ever compromised

---

## Complete Automated Script

I'll create `gmail_oauth_reauthenticate.py` that does all of this.

