#!/usr/bin/env python3
"""ww gen-video set-privacy — Change an uploaded YouTube video's privacy status.

Changes privacyStatus of an existing video on YouTube via the YouTube Data API v3.

Requires:
  pip install google-api-python-client google-auth-oauthlib

Setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project → Enable YouTube Data API v3
  3. Create OAuth 2.0 credentials (Desktop app type)
  4. Save as ~/.google/client_secret.json
"""

import sys
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# youtube scope (broader than youtube.upload) needed for updating videos
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def _get_credentials(credential_file=None):
    """Get or refresh YouTube API credentials for video update.

    Default credential path: ~/.google/client_secret.json
    Token cache: ~/.google/youtube_update_token.json
    (Separate token from upload to avoid scope conflicts)
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    home = Path.home()
    google_dir = home / ".google"
    google_dir.mkdir(parents=True, exist_ok=True)

    if credential_file is None:
        credential_file = str(google_dir / "client_secret.json")

    token_file = google_dir / "youtube_update_token.json"
    credentials = None

    # Load cached token
    if token_file.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            credentials = None

    # Refresh or get new credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    elif not credentials or not credentials.valid:
        if not Path(credential_file).is_file():
            print(f"Error: Google OAuth client secret not found at {credential_file}")
            print()
            print("To set up YouTube API:")
            print("1. Go to https://console.cloud.google.com/")
            print("2. Create a project -> Enable YouTube Data API v3")
            print("3. Create OAuth 2.0 credentials (Desktop app type)")
            print("4. Download the JSON and save it as:")
            print(f"   {credential_file}")
            print("5. In Google Cloud Console, add this Authorized redirect URI:")
            print("   http://localhost:8080/")
            print()
            sys.exit(1)

        flow = InstalledAppFlow.from_client_secrets_file(credential_file, SCOPES)
        print("Opening browser for Google OAuth...")
        credentials = flow.run_local_server(port=8080)

    # Save token for next run
    with open(token_file, "w") as f:
        f.write(credentials.to_json())

    return credentials


def main():
    try:
        from fluxreel.env import load_env as _le

        _le()
    except ImportError:
        pass

    args = list(sys.argv[1:])

    # ── Help ────────────────────────────────────────────────────────────────
    if not args or "--help" in args or "-h" in args:
        print("Usage: ww gen-video set-privacy <video_id> <public|unlisted|private>")
        print()
        print("Change the privacy status of an already-uploaded YouTube video.")
        print()
        print("Arguments:")
        print("  video_id      YouTube video ID (from the URL after ?v= or youtu.be/)")
        print("  privacy       One of: public, unlisted, private")
        print()
        print("Options:")
        print("  --credential PATH  Path to Google OAuth client_secret.json")
        print()
        print("Examples:")
        print("  ww gen-video set-privacy dQw4w9WgXcQ public")
        print("  ww gen-video set-privacy dQw4w9WgXcQ unlisted")
        return

    if len(args) < 2:
        print("Error: Both video_id and privacy status are required.")
        print("Usage: ww gen-video set-privacy <video_id> <public|unlisted|private>")
        sys.exit(1)

    video_id = args[0]
    privacy_status = args[1].lower()

    if privacy_status not in ("public", "unlisted", "private"):
        print(f"Error: Invalid privacy status '{privacy_status}'.")
        print("Must be one of: public, unlisted, private")
        sys.exit(1)

    credential_file = None
    if len(args) > 2 and args[2] == "--credential" and len(args) > 3:
        credential_file = args[3]

    print(f"Video ID: {video_id}")
    print(f"New privacy: {privacy_status}")
    print()

    # ── Authenticate and update ─────────────────────────────────────────────
    print("Authenticating with Google...")
    credentials = _get_credentials(credential_file)

    print("Building YouTube API client...")
    youtube = build("youtube", "v3", credentials=credentials)

    # First, fetch the current video to get the full snippet and status
    print(f"Fetching video {video_id}...")
    try:
        video_response = (
            youtube.videos().list(part="snippet,status", id=video_id).execute()
        )
    except HttpError as e:
        detail = e.content.decode() if hasattr(e, "content") and e.content else str(e)
        print(f"Error: YouTube API returned HTTP {e.status_code}")
        print(f"Details: {detail}")
        sys.exit(1)

    items = video_response.get("items", [])
    if not items:
        print(f"Error: Video {video_id} not found or access denied.")
        sys.exit(1)

    video = items[0]

    # Update only the privacy status, keep everything else
    video["status"]["privacyStatus"] = privacy_status

    print(f"Updating privacy to {privacy_status}...")
    try:
        update_response = (
            youtube.videos()
            .update(
                part="status",
                body={
                    "id": video_id,
                    "status": video["status"],
                },
            )
            .execute()
        )
    except HttpError as e:
        detail = e.content.decode() if hasattr(e, "content") and e.content else str(e)
        print(f"Error: YouTube API returned HTTP {e.status_code}")
        print(f"Details: {detail}")
        sys.exit(1)

    new_status = update_response.get("status", {}).get("privacyStatus", "unknown")
    url = f"https://youtu.be/{video_id}"
    print(f"\nDone! Video is now {new_status}.")
    print(f"  URL: {url}")
