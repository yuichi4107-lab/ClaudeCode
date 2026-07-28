"""初回だけ実行: ブラウザで OAuth 承認して token.json を保存する。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

from core.config import Config


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    load_dotenv()
    cfg = Config.load()
    client_secret = Path(cfg.gmail_oauth_client_secret_json)
    if not client_secret.exists():
        print(f"[ERR] {client_secret} not found. Google Cloud Console からOAuthクライアント作成→JSONダウンロードしてください。")
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path = Path(cfg.gmail_oauth_token_json)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"[OK] token saved to {token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
