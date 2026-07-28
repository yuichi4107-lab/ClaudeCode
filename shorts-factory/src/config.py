"""shorts-factory 設定ローダー。

優先順位: 環境変数 > ~/shorts-factory/config.yaml > DEFAULTS
秘密情報は ~/shorts-factory/secrets.yaml（Drive外）に置く。
SNS認証は既存の .company/engineering/sns-credentials/.env を参照する。
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

RUNTIME_DIR = Path(os.environ.get("SHORTS_RUNTIME_DIR", str(Path.home() / "shorts-factory")))


def _is_drive_path(path: Path) -> bool:
    return "/Library/CloudStorage/" in str(path).replace("\\", "/")


def _resolve_repo_root() -> Path:
    # runtime import時に候補へexists()すると、それだけでDrive File Providerが
    # 固まる。ミラー先は明示値を文字列として保持し、ここではstatしない。
    for key in ("SHORTS_DRIVE_MIRROR_ROOT", "SHORTS_REPO_ROOT", "YNFACTORY_ROOT"):
        if os.environ.get(key):
            return Path(os.environ[key]).expanduser()
    here = Path(__file__).resolve()
    return here.parents[2] if len(here.parents) > 2 else here.parent


# Drive上のリポジトリルート。runtimeのホットパスでは触らず、非同期ミラーのみで使う。
DEFAULT_REPO_ROOT = _resolve_repo_root()


def _resolve_factory_root(repo_root: Path) -> Path:
    """Return local code/assets root without touching Drive during normal runs."""
    if os.environ.get("SHORTS_FACTORY_ROOT"):
        return Path(os.environ["SHORTS_FACTORY_ROOT"]).expanduser()
    return Path(__file__).resolve().parents[1]

DEFAULTS: dict = {
    "speaker_id": 3,  # ずんだもん（ノーマル）
    "speaker_credit": "VOICEVOX:ずんだもん",
    "speed_scale": 1.0,
    "llm": {
        "provider": "claude_cli",  # claude_cli | openai
        "claude_bin": "/Users/yuichi/.local/bin/claude",
        "claude_model": "",  # 空 = CLIデフォルト
        "openai_model": "gpt-5.1",
        "timeout_sec": 300,
        "retries": 3,
    },
    "images": {
        "provider": "card",  # card | openai | gemini （キー投入でAI画像へ切替）
        "count": 4,
        "openai_model": "gpt-image-2",
        "openai_quality": "medium",
        "gemini_model": "gemini-3.1-flash-image-preview",
    },
    "video": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "crf": 23,
        "min_sec": 30,
        "max_sec": 60,
        "max_mb": 50,
        "xfade_sec": 0.5,
        "lead_in_sec": 0.4,
        "tail_sec": 0.8,
        "cue_gap_sec": 0.18,
    },
    "subtitle": {
        "font": "Noto Sans JP",
        "fontsize": 76,
        "max_chars_per_line": 13,
        "margin_v": 600,
    },
    "tts": {
        "engine_dir": str(RUNTIME_DIR / "voicevox"),
        "host": "127.0.0.1",
        "port": 50021,
        "output_sampling_rate": 48000,
        "kana_mismatch_cer": 0.15,  # これを超えたら読み仮名直読みに切替
    },
    "verify": {
        "whisper_provider": "local",  # local | openai
        "whisper_bin": "/opt/homebrew/bin/whisper-cli",
        "whisper_model": str(RUNTIME_DIR / "models" / "ggml-large-v3-turbo.bin"),
        "cer_line_max": 0.20,
        "cer_avg_max": 0.10,
        "lufs_target": -14.0,
        "lufs_tol": 2.0,
        "max_fix_loops": 5,
        "auto_remake_on_fail": True,
        "remake_max_attempts": 2,
    },
    "queue": {
        "auto_post": False,  # True で承認スキップ → 即投稿
        "platforms": ["x"],  # x | youtube | instagram | tiktok（工程進行で追加）
        "retry_failed_posts": True,  # 投稿失敗時、失敗媒体だけ自動再投稿
        "retry_max_attempts": 2,  # 初回失敗後の自動再投稿回数
        "retry_delay_sec": 60,  # 再投稿前の待機秒数
        "auto_recover_failed_posts": True,  # 2回再試行後に原因確認・復旧してから再投稿
        "recovery_after_retries": 2,
        "recovery_retry_attempts": 1,
        "recovery_max_attempts_per_platform": 2,
        "deferred_retry_failed_posts": True,  # 即時再試行後に失敗媒体だけ遅延再投稿
        "deferred_retry_delay_sec": 900,
        "deferred_retry_max_attempts": 3,
        "deferred_retry_window_hours": 6,
    },
    "cta": {
        "lp_url": "https://ai.yn-factory.com/",
        "campaign": "shorts_ai_consult",
    },
    "youtube": {
        "cdp_port": 9223,
    },
    "tiktok": {
        "cdp_port": 9224,
        "profile_dir": str(RUNTIME_DIR / ".auth" / "tiktok-chrome"),
    },
    "content": {
        "default_difficulty": "beginner",
        "platform_variant_videos": False,
        "scheduled_slots": [
            {"hour": 9, "minute": 0, "difficulty": "beginner"},
            {"hour": 14, "minute": 0, "difficulty": "intermediate"},
            {"hour": 19, "minute": 0, "difficulty": "intermediate"},
        ],
    },
    "topics": {
        "auto_replenish": {
            "enabled": True,
            "min_by_difficulty": {
                "beginner": 8,
                "intermediate": 16,
            },
            "target_by_difficulty": {
                "beginner": 18,
                "intermediate": 36,
            },
        }
    },
    "seedance": {
        "enabled": True,  # False にすると枠判定に関わらず常に静止画版
        "slots": ["mon-09", "wed-14", "fri-19", "sat-14", "sun-09"],  # 週5枠（曜日-時）
        "model": "fast",  # std ($0.112/s) | fast ($0.09/s)
        "resolution": "720p",
        "ratio": "9:16",
        "audio_mode": "voicevox",  # voicevox | native
        "generate_audio": False,  # 音声はVOICEVOXで差し替え、Seedance音声は使わない
        "voicevox_speaker_id": 13,  # 青山龍星（ノーマル）
        "voicevox_speaker_credit": "VOICEVOX:青山龍星",
        "watermark": False,
        "seed": 42,  # 固定するとスタイルの一貫性が上がる
        "cut_duration_sec": 10,
        "poll_interval_sec": 15,
        "timeout_sec": 1800,  # 1カットあたりのポーリングタイムアウト（30分）
        "monthly_budget_usd": 130.0,
        "max_cost_per_video_usd": 10.0,
        "cer_line_max": 0.30,  # Seedance音声はVOICEVOXよりCER許容を緩める
        "cer_avg_max": 0.18,
        "remake_max_attempts": 1,  # CER不合格時、再生成は1回だけ（それでもダメならフォールバック）
    },
    "telegram": {"enabled": True},
    "ffmpeg": "/Users/yuichi/bin/ffmpeg",
    "ffprobe": "/opt/homebrew/bin/ffprobe",
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class Config:
    def __init__(self) -> None:
        self.runtime_dir = RUNTIME_DIR
        if _is_drive_path(self.runtime_dir):
            raise RuntimeError(f"SHORTS_RUNTIME_DIR must be local: {self.runtime_dir}")
        self.repo_root = DEFAULT_REPO_ROOT
        self.cfg = _deep_merge(DEFAULTS, _load_yaml(RUNTIME_DIR / "config.yaml"))
        self.secrets = _load_yaml(RUNTIME_DIR / "secrets.yaml")

        # コード/実行状態はローカルを正本にする。repo_root配下は非同期ミラー先。
        self.factory_dir = _resolve_factory_root(self.repo_root)
        self.assets_dir = self.factory_dir / "assets"
        self.fonts_dir = self.assets_dir / "fonts"
        self.prompts_dir = self.factory_dir / "prompts"

        self.state_dir = self.runtime_dir / "state"
        self.marketing_dir = self.state_dir
        self.queue_dir = self.marketing_dir / "queue"
        self.topics_path = self.marketing_dir / "topics.json"
        self.outputs_dir = self.runtime_dir / "outputs"
        self.work_dir = self.runtime_dir / "work"
        self.logs_dir = self.runtime_dir / "logs"

        self.drive_marketing_dir = (
            self.repo_root / ".company" / "marketing" / "shorts-factory"
        )
        self.drive_queue_dir = self.drive_marketing_dir / "queue"
        self.drive_topics_path = self.drive_marketing_dir / "topics.json"
        self.drive_outputs_dir = (
            self.repo_root / ".company" / "outputs" / "shorts-factory"
        )
        self.drive_sns_env_path = (
            self.repo_root / ".company" / "engineering" / "sns-credentials" / ".env"
        )
        self.sns_env_path = self.runtime_dir / "sns_credentials" / ".env"
        self.mirror_dir = self.runtime_dir / "drive_mirror"
        self.mirror_manifest_path = self.mirror_dir / "manifest.json"
        self.runtime_ready_marker = self.state_dir / "migration-v2-local-control-plane.json"

        for d in (
            self.state_dir,
            self.queue_dir,
            self.outputs_dir,
            self.work_dir,
            self.logs_dir,
            self.sns_env_path.parent,
            self.mirror_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # --- 取得ヘルパ ---
    def get(self, *keys, default=None):
        cur = self.cfg
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def secret(self, *keys, default=None):
        cur = self.secrets
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def assert_runtime_ready(self) -> None:
        hot_paths = {
            "factory_dir": self.factory_dir,
            "state_dir": self.state_dir,
            "queue_dir": self.queue_dir,
            "topics_path": self.topics_path,
            "outputs_dir": self.outputs_dir,
            "work_dir": self.work_dir,
            "logs_dir": self.logs_dir,
            "sns_env_path": self.sns_env_path,
        }
        invalid = [
            name
            for name, path in hot_paths.items()
            if _is_drive_path(path)
        ]
        if invalid:
            raise RuntimeError(
                "Drive path configured in runtime hot path: " + ", ".join(invalid)
            )
        if os.environ.get("SHORTS_ALLOW_UNMIGRATED") == "1":
            return
        if not self.runtime_ready_marker.is_file():
            raise RuntimeError(
                "local runtime state is not migrated; run scripts/migrate_runtime_state.py"
            )
        if not self.topics_path.is_file() or not self.queue_dir.is_dir():
            raise RuntimeError("local runtime state is incomplete")

    @property
    def openai_api_key(self) -> str | None:
        return os.environ.get("OPENAI_API_KEY") or self.secret("openai_api_key") or None

    @property
    def gemini_api_key(self) -> str | None:
        return os.environ.get("GEMINI_API_KEY") or self.secret("gemini_api_key") or None

    @property
    def atlas_cloud_api_key(self) -> str | None:
        return os.environ.get("ATLAS_CLOUD_API_KEY") or self.secret("atlas_cloud", "api_key") or None

    @property
    def telegram_token(self) -> str | None:
        return os.environ.get("SHORTS_TG_TOKEN") or self.secret("telegram", "bot_token")

    @property
    def telegram_chat_id(self) -> str | None:
        v = os.environ.get("SHORTS_TG_CHAT_ID") or self.secret("telegram", "chat_id")
        return str(v) if v is not None else None


CONFIG = Config()
