"""Credentials for the Google Sheets / Drive APIs.

Three modes, chosen by --auth:
  oauth    Desktop OAuth client (credentials.json) -> browser consent once -> token.json cached.
           Reads any sheet YOUR Google account can open. Best for personal practice.
  service  Service-account key JSON. Reads any sheet SHARED WITH the service account's email.
           Best for headless/automated runs.
  export   No credentials. Downloads the workbook as .xlsx through the public export URL.
           Works only when the sheet is link-shared ("Anyone with the link").
See SETUP_GOOGLE_API.md for the console clicks.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONFIG_DIR = Path(os.environ.get("SD_CONFIG_DIR", Path.home() / ".config" / "sheets_decomposer"))
OAUTH_CLIENT = Path(os.environ.get("SD_OAUTH_CLIENT", CONFIG_DIR / "credentials.json"))
OAUTH_TOKEN = Path(os.environ.get("SD_OAUTH_TOKEN", CONFIG_DIR / "token.json"))
SERVICE_ACCOUNT = Path(os.environ.get("SD_SERVICE_ACCOUNT", CONFIG_DIR / "service_account.json"))

SCOPES_RO = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
SCOPES_RW = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def oauth_credentials(write: bool = False, open_browser: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    scopes = SCOPES_RW if write else SCOPES_RO
    creds = None
    if OAUTH_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN), scopes)
        if creds and set(scopes) - set(creds.scopes or []):
            creds = None  # token was issued for narrower scopes; re-consent
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not OAUTH_CLIENT.exists():
            raise SystemExit(
                f"OAuth client file not found: {OAUTH_CLIENT}\n"
                "Download the Desktop-app OAuth client JSON from Google Cloud Console "
                "(APIs & Services -> Credentials) and save it there. See SETUP_GOOGLE_API.md."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(OAUTH_CLIENT), scopes)
        # WSL: the local server still works; if no browser opens, copy the printed URL
        # into Windows Chrome. The redirect back to localhost is reachable from Windows.
        creds = flow.run_local_server(port=0, open_browser=open_browser, prompt="consent")
        OAUTH_TOKEN.parent.mkdir(parents=True, exist_ok=True)
        OAUTH_TOKEN.write_text(creds.to_json())
        try:
            OAUTH_TOKEN.chmod(0o600)
        except OSError:
            pass
    return creds


def service_account_credentials(write: bool = False):
    from google.oauth2 import service_account

    if not SERVICE_ACCOUNT.exists():
        raise SystemExit(
            f"Service account key not found: {SERVICE_ACCOUNT}\n"
            "Create one in Google Cloud Console (IAM & Admin -> Service Accounts -> Keys) "
            "and share the target sheet with the service account's email. See SETUP_GOOGLE_API.md."
        )
    return service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT), scopes=SCOPES_RW if write else SCOPES_RO
    )


def get_credentials(mode: str = "oauth", write: bool = False):
    if mode == "oauth":
        return oauth_credentials(write=write)
    if mode == "service":
        return service_account_credentials(write=write)
    raise ValueError(f"unknown auth mode {mode!r}")


def build_services(mode: str = "oauth", write: bool = False):
    """Return (sheets_service, drive_service)."""
    from googleapiclient.discovery import build

    creds = get_credentials(mode, write)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return sheets, drive
