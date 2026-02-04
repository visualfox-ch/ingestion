#!/usr/bin/env python3
"""
Run this script LOCALLY (not in Docker) to authorize Google Calendar.
It will open your browser, complete OAuth, and save the token.

Usage:
    python setup_calendar_local.py projektil /path/to/credentials_projektil.json
    python setup_calendar_local.py visualfox /path/to/credentials_visualfox.json

The token file will be saved as <account_name>.json in the current directory.
Copy it to your NAS: /volume1/BRAIN/system/secrets/calendars/
"""
import sys
import json
from pathlib import Path

# Install if needed: pip install google-auth-oauthlib google-api-python-client
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def main():
    if len(sys.argv) < 3:
        print("Usage: python setup_calendar_local.py <account_name> <credentials_file>")
        print("Example: python setup_calendar_local.py projektil ./credentials_projektil.json")
        sys.exit(1)

    account_name = sys.argv[1]
    credentials_path = Path(sys.argv[2])

    if not credentials_path.exists():
        print(f"Error: Credentials file not found: {credentials_path}")
        sys.exit(1)

    token_path = Path(f"{account_name}.json")

    print(f"Setting up calendar account: {account_name}")
    print(f"Using credentials: {credentials_path}")
    print(f"Token will be saved to: {token_path}")
    print()

    # Run OAuth flow - this will open your browser
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)

    # Save token
    token_path.write_text(creds.to_json())
    print(f"\nToken saved to: {token_path}")

    # Test connection
    service = build("calendar", "v3", credentials=creds)
    calendars = service.calendarList().list().execute()
    print(f"\nConnected! Found {len(calendars.get('items', []))} calendars:")
    for cal in calendars.get("items", [])[:5]:
        print(f"  - {cal.get('summary')} ({cal.get('id')})")

    print(f"\n" + "=" * 60)
    print(f"Now copy {token_path} to your NAS:")
    print(f"  scp {token_path} micha@192.168.1.103:/volume1/BRAIN/system/secrets/calendars/")
    print("=" * 60)


if __name__ == "__main__":
    main()
