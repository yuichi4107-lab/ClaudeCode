# -*- coding: utf-8 -*-
"""共通: 設定・状態・台帳・通知"""
import csv
import json
import os
import datetime as dt

import requests
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def state_path(cfg, name):
    d = os.path.join(BASE, cfg["paths"]["state_dir"])
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def load_state(cfg, name, default):
    p = state_path(cfg, name)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            notify(f"⚠️ quant-bot: 状態ファイル {name} が破損しています（{e}）。"
                   f"初期値で続行します。ポジション状態の手動確認が必要です")
    return default


def save_state(cfg, name, obj):
    p = state_path(cfg, name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, p)


def append_ledger(cfg, row: dict):
    p = state_path(cfg, "ledger.csv")
    exists = os.path.exists(p)
    with open(p, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            w.writeheader()
        w.writerow(row)


def notify(text: str):
    """Telegram通知。.env の TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID を使用。
    未設定時は標準出力のみ（ローカルテスト用）。"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    envp = os.path.join(BASE, ".env")
    if (not token or not chat) and os.path.exists(envp):
        with open(envp, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k == "TELEGRAM_BOT_TOKEN":
                        token = token or v.strip()
                    if k == "TELEGRAM_CHAT_ID":
                        chat = chat or v.strip()
    print("[notify]", text.replace("\n", " | "))
    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text}, timeout=20)
        except Exception as e:
            print("telegram error:", e)


def today_jst():
    return (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()
