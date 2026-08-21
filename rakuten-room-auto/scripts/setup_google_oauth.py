#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_secret = Path(os.path.expanduser(os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "~/rakuten-room-auto/secrets/google-oauth-client.json")))
    token_path = Path(os.path.expanduser(os.environ.get("GOOGLE_TOKEN_JSON", "~/rakuten-room-auto/secrets/google-token.json")))
    if not client_secret.exists():
        print(f"[ERR] OAuth client JSON not found: {client_secret}")
        return 1
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"[OK] token saved: {token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
