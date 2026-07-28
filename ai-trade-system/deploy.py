"""ai-trade-system を ConoHa VPS にデプロイするスクリプト"""
import os
import sys
import tarfile
import tempfile
from fabric import Connection

VPS_HOST = "tools.ynfactory.online"
VPS_USER = "root"
VPS_PASS = os.environ.get("VPS_ROOT_PW", "")  # 2026-05-30 ハードコード除去。環境変数で供給
REMOTE_DIR = "/opt/ai-trade-system"

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# 転送対象ファイル
INCLUDE_FILES = [
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    "requirements.txt",
    ".env",
    "src/",
    # data/positions.json と trade_history.json は VPS上の実データを保持するため除外
    "data/ohlcv/BTC-USDT_1d_1000.json",
]

INCLUDE_DIRS = [
    "src/",
    "scripts/",
    "results/fx_phase1/",
]


def create_tarball():
    """デプロイ用のtar.gzを作成"""
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    with tarfile.open(tmp.name, "w:gz") as tar:
        for item in INCLUDE_FILES:
            full_path = os.path.join(PROJECT_DIR, item)
            if os.path.exists(full_path):
                tar.add(full_path, arcname=f"ai-trade-system/{item}")
                print(f"  + {item}")
            else:
                print(f"  SKIP (not found): {item}")

        # src/ ディレクトリを丸ごと追加
        src_dir = os.path.join(PROJECT_DIR, "src")
        for root, dirs, files in os.walk(src_dir):
            for f in files:
                if f.endswith((".py", ".txt", ".json")):
                    full = os.path.join(root, f)
                    arcname = "ai-trade-system/" + os.path.relpath(full, PROJECT_DIR).replace("\\", "/")
                    tar.add(full, arcname=arcname)

        # scripts/ ディレクトリを丸ごと追加（forward 関連スクリプト含む）
        scripts_dir = os.path.join(PROJECT_DIR, "scripts")
        if os.path.exists(scripts_dir):
            for root, dirs, files in os.walk(scripts_dir):
                for f in files:
                    if f.endswith((".py", ".sh", ".txt")):
                        full = os.path.join(root, f)
                        arcname = "ai-trade-system/" + os.path.relpath(full, PROJECT_DIR).replace("\\", "/")
                        tar.add(full, arcname=arcname)
                        print(f"  + scripts/{f}")

        # results/fx_phase1/ ディレクトリを追加（portfolio_config.json等）
        results_dir = os.path.join(PROJECT_DIR, "results", "fx_phase1")
        if os.path.exists(results_dir):
            for root, dirs, files in os.walk(results_dir):
                for f in files:
                    if f.endswith((".json", ".md")):
                        full = os.path.join(root, f)
                        arcname = "ai-trade-system/" + os.path.relpath(full, PROJECT_DIR).replace("\\", "/")
                        tar.add(full, arcname=arcname)
            print(f"  + results/fx_phase1/")

    print(f"\n  Archive: {tmp.name} ({os.path.getsize(tmp.name) / 1024:.0f} KB)")
    return tmp.name


def deploy():
    print("=" * 50)
    print("  AI Trader Deploy to ConoHa VPS")
    print("=" * 50)

    # 1. tar.gz作成
    print("\n[1] Creating archive...")
    archive = create_tarball()

    # 2. VPS接続
    print(f"\n[2] Connecting to {VPS_HOST}...")
    c = Connection(VPS_HOST, user=VPS_USER, connect_kwargs={"password": VPS_PASS})

    # 3. リモートディレクトリ準備
    print(f"\n[3] Preparing {REMOTE_DIR}...")
    c.run(f"mkdir -p {REMOTE_DIR}", hide=True)

    # 4. ファイル転送
    print(f"\n[4] Uploading archive...")
    c.put(archive, f"/tmp/ai-trade-system.tar.gz")
    c.run(f"cd /opt && tar xzf /tmp/ai-trade-system.tar.gz && rm /tmp/ai-trade-system.tar.gz", hide=True)

    # 5. data ディレクトリ準備
    print(f"\n[5] Preparing data directory...")
    c.run(f"mkdir -p {REMOTE_DIR}/data/signals {REMOTE_DIR}/data/ohlcv", hide=True)

    # 6. Docker build & up
    print(f"\n[6] Building and starting container...")
    result = c.run(f"cd {REMOTE_DIR} && docker compose down 2>/dev/null; docker compose up -d --build 2>&1", hide=True)
    print(f"  Build output (last 10 lines):")
    for line in result.stdout.strip().split("\n")[-10:]:
        print(f"    {line}")

    # 7. 確認
    print(f"\n[7] Verifying...")
    result = c.run(f"docker ps --filter name=ai-trader --format '{{{{.Status}}}}'", hide=True)
    print(f"  Container status: {result.stdout.strip()}")

    result = c.run(f"docker logs ai-trader --tail 5 2>&1", hide=True)
    print(f"  Recent logs:\n{result.stdout}")

    # クリーンアップ
    os.unlink(archive)

    print("\n" + "=" * 50)
    print("  Deploy complete!")
    print(f"  Monitor: ssh root@{VPS_HOST} docker logs -f ai-trader")
    print("=" * 50)


if __name__ == "__main__":
    deploy()
