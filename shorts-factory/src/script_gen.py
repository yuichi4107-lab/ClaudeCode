"""台本生成。

デフォルトは claude CLI ヘッドレス実行（このMacで認証済み・APIキー不要）。
secrets.yaml に openai_api_key を入れて llm.provider=openai にすれば
OpenAI Structured Outputs へ切替できる。

生成物はバリデータで機械検証し、違反があればエラー内容をフィードバックして
再生成する（最大 llm.retries 回）。字幕正確性の「生成層」防御。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

from .config import CONFIG
from .fs_retry import is_transient_io_error, retry_io
from .jp_text import fold_aliases, lcs_coverage, phonetic_cer, phonetic_hira
from . import topic_store

SCRIPT_SCHEMA_KEYS = {"title", "cues", "caption", "hashtags", "card_keywords"}
_KANA_RE = re.compile(r"^[ァ-ヶー、。・\s０-９0-9？?！!]+$")
_UNSTABLE_SPEECH_RE = re.compile(r"[A-Za-z%％]")
_SPEECH_TERM_REPLACEMENTS = {
    "chatgpt": "チャットジーピーティー",
    "claude": "クロード",
    "gemini": "ジェミニ",
    "perplexity": "パープレキシティ",
    "notebooklm": "ノートブックエルエム",
    "notebook lm": "ノートブックエルエム",
    "google drive": "グーグルドライブ",
    "google docs": "グーグルドキュメント",
    "google sheets": "グーグルスプレッドシート",
    "google slides": "グーグルスライド",
    "canva": "キャンバ",
    "gamma": "ガンマ",
    "figma": "フィグマ",
    "zapier": "ザピアー",
    "make": "メイク",
    "n8n": "エヌエイトエヌ",
    "openai": "オープンエーアイ",
    "copilot": "コパイロット",
    "youtube": "ユーチューブ",
    "instagram": "インスタグラム",
    "tiktok": "ティックトック",
    "excel": "エクセル",
    "google": "グーグル",
    "gmail": "ジーメール",
    "notion": "ノーション",
    "slack": "スラック",
    "zoom": "ズーム",
    "teams": "チームズ",
    "word": "ワード",
    "powerpoint": "パワーポイント",
    "pdf": "ピーディーエフ",
    "api": "エーピーアイ",
    "sns": "エスエヌエス",
    "kpi": "ケーピーアイ",
    "crm": "シーアールエム",
    "csv": "シーエスブイ",
    "url": "ユーアールエル",
    "llm": "エルエルエム",
    "dx": "ディーエックス",
    "it": "アイティー",
    "ec": "イーシー",
    "ai": "エーアイ",
    "%": "パーセント",
    "％": "パーセント",
}
_SPEECH_TERM_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_SPEECH_TERM_REPLACEMENTS, key=len, reverse=True)),
    re.IGNORECASE,
)
_DISPLAY_CANONICAL_TERMS = {
    "チャットジーピーティー": "ChatGPT",
    "チャットジィーピィーティィー": "ChatGPT",
    "チャットGPT": "ChatGPT",
    "chatgpt": "ChatGPT",
    "Claude": "Claude",
    "claude": "Claude",
    "クロード": "Claude",
    "Gemini": "Gemini",
    "gemini": "Gemini",
    "ジェミニ": "Gemini",
    "Perplexity": "Perplexity",
    "perplexity": "Perplexity",
    "パープレキシティ": "Perplexity",
    "NotebookLM": "NotebookLM",
    "notebooklm": "NotebookLM",
    "notebook lm": "NotebookLM",
    "ノートブックエルエム": "NotebookLM",
    "Canva": "Canva",
    "canva": "Canva",
    "キャンバ": "Canva",
    "Gamma": "Gamma",
    "gamma": "Gamma",
    "ガンマ": "Gamma",
    "Figma": "Figma",
    "figma": "Figma",
    "フィグマ": "Figma",
    "Zapier": "Zapier",
    "zapier": "Zapier",
    "ザピアー": "Zapier",
    "Make": "Make",
    "make": "Make",
    "メイク": "Make",
    "n8n": "n8n",
    "エヌエイトエヌ": "n8n",
    "OpenAI": "OpenAI",
    "openai": "OpenAI",
    "オープンエーアイ": "OpenAI",
    "Copilot": "Copilot",
    "copilot": "Copilot",
    "コパイロット": "Copilot",
    "Google Drive": "Google Drive",
    "google drive": "Google Drive",
    "グーグルドライブ": "Google Drive",
    "Google Docs": "Google Docs",
    "google docs": "Google Docs",
    "グーグルドキュメント": "Google Docs",
    "Google Sheets": "Google Sheets",
    "google sheets": "Google Sheets",
    "グーグルスプレッドシート": "Google Sheets",
    "Google Slides": "Google Slides",
    "google slides": "Google Slides",
    "グーグルスライド": "Google Slides",
    "Google": "Google",
    "google": "Google",
    "グーグル": "Google",
    "Gmail": "Gmail",
    "gmail": "Gmail",
    "ジーメール": "Gmail",
    "Notion": "Notion",
    "notion": "Notion",
    "ノーション": "Notion",
    "Slack": "Slack",
    "slack": "Slack",
    "スラック": "Slack",
    "Zoom": "Zoom",
    "zoom": "Zoom",
    "ズーム": "Zoom",
    "Teams": "Teams",
    "teams": "Teams",
    "チームズ": "Teams",
    "Excel": "Excel",
    "excel": "Excel",
    "エクセル": "Excel",
    "Word": "Word",
    "word": "Word",
    "ワード": "Word",
    "PowerPoint": "PowerPoint",
    "powerpoint": "PowerPoint",
    "パワーポイント": "PowerPoint",
    "PDF": "PDF",
    "pdf": "PDF",
    "ピーディーエフ": "PDF",
    "API": "API",
    "api": "API",
    "エーピーアイ": "API",
    "SNS": "SNS",
    "sns": "SNS",
    "エスエヌエス": "SNS",
    "KPI": "KPI",
    "kpi": "KPI",
    "ケーピーアイ": "KPI",
    "CRM": "CRM",
    "crm": "CRM",
    "シーアールエム": "CRM",
    "CSV": "CSV",
    "csv": "CSV",
    "シーエスブイ": "CSV",
    "URL": "URL",
    "url": "URL",
    "ユーアールエル": "URL",
    "LLM": "LLM",
    "llm": "LLM",
    "エルエルエム": "LLM",
    "DX": "DX",
    "dx": "DX",
    "ディーエックス": "DX",
    "IT": "IT",
    "it": "IT",
    "アイティー": "IT",
    "EC": "EC",
    "ec": "EC",
    "イーシー": "EC",
    "YouTube": "YouTube",
    "youtube": "YouTube",
    "ユーチューブ": "YouTube",
    "Instagram": "Instagram",
    "instagram": "Instagram",
    "インスタグラム": "Instagram",
    "TikTok": "TikTok",
    "tiktok": "TikTok",
    "ティックトック": "TikTok",
    "AI": "AI",
    "ai": "AI",
    "エーアイ": "AI",
}
_DISPLAY_CANONICAL_TERM_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(_DISPLAY_CANONICAL_TERMS, key=len, reverse=True)),
    re.IGNORECASE,
)
_ALLOWED_DISPLAY_LATIN_TERMS = tuple(
    sorted(set(_DISPLAY_CANONICAL_TERMS.values()), key=len, reverse=True)
)
_ALLOWED_DISPLAY_LATIN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    + "|".join(re.escape(term) for term in _ALLOWED_DISPLAY_LATIN_TERMS)
    + r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _speech_unstable_text(s: str) -> bool:
    return bool(_UNSTABLE_SPEECH_RE.search(s.replace("ChatGPT", "")))


def _replace_unstable_terms(text: str) -> str:
    return _SPEECH_TERM_RE.sub(
        lambda m: _SPEECH_TERM_REPLACEMENTS[m.group(0).lower()],
        text,
    )


def _normalize_display_terms(text: str) -> str:
    text = unicodedata.normalize("NFKC", _replace_unstable_terms(text))
    return _DISPLAY_CANONICAL_TERM_RE.sub(
        lambda m: _DISPLAY_CANONICAL_TERMS.get(m.group(0), _DISPLAY_CANONICAL_TERMS[m.group(0).lower()]),
        text,
    )


def _display_unstable_text(s: str) -> bool:
    stripped = _ALLOWED_DISPLAY_LATIN_RE.sub("", s)
    return bool(_UNSTABLE_SPEECH_RE.search(stripped))


def normalize_generated_script(data: dict) -> dict:
    """Normalize common English abbreviations before validation/TTS."""
    if not isinstance(data, dict):
        return data
    cues = data.get("cues")
    if not isinstance(cues, list):
        return data
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        display = cue.get("display")
        if isinstance(display, list):
            cue["display"] = [
                _normalize_display_terms(line) if isinstance(line, str) else line
                for line in display
            ]
        for key in ("tts_text", "reading_kana"):
            if isinstance(cue.get(key), str):
                cue[key] = _replace_unstable_terms(cue[key])
        # tts_kana（Seedance版のカタカナ読み）は jp_text.TERM_READINGS
        # （ChatGPT→チャットジーピーティー等、既存のVOICEVOXユーザー辞書と
        # 共通の読み辞書）で英字残存を機械的にカタカナへ畳み込む。
        if isinstance(cue.get("tts_kana"), str):
            cue["tts_kana"] = fold_aliases(cue["tts_kana"])
    return data


def _char_width(s: str) -> int:
    """全角=1, 半角=0.5 で数える（字幕13文字制限は全角換算）。"""
    w = 0.0
    for ch in s:
        w += 1.0 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 0.5
    return int(w + 0.999)


def validate_script(data: dict, image_count: int) -> list[str]:
    """台本JSONの機械検証。問題点のリストを返す（空なら合格）。"""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["JSONオブジェクトではない"]
    missing = SCRIPT_SCHEMA_KEYS - set(data)
    if missing:
        errs.append(f"必須キー欠落: {sorted(missing)}")
        return errs

    title = data["title"]
    if not isinstance(title, str) or not (4 <= len(title) <= 32):
        errs.append("title は4〜32文字の文字列にすること")

    cues = data["cues"]
    if not isinstance(cues, list) or not (8 <= len(cues) <= 16):
        errs.append(f"cues は8〜16個にすること（現在 {len(cues) if isinstance(cues, list) else '不正'}）")
        return errs

    total_kana = 0
    max_line = CONFIG.get("subtitle", "max_chars_per_line", default=13)
    for i, cue in enumerate(cues):
        if not isinstance(cue, dict):
            errs.append(f"cue[{i}] がオブジェクトでない")
            continue
        disp = cue.get("display")
        if not isinstance(disp, list) or not (1 <= len(disp) <= 2):
            errs.append(f"cue[{i}].display は1〜2行の配列にすること")
        else:
            for j, line in enumerate(disp):
                if not isinstance(line, str) or not line.strip():
                    errs.append(f"cue[{i}].display[{j}] が空")
                elif _char_width(line) > max_line:
                    errs.append(
                        f"cue[{i}].display[{j}]「{line}」が{_char_width(line)}文字で上限{max_line}文字超過。短く分割すること"
                    )
                elif _display_unstable_text(line):
                    errs.append(
                        f"cue[{i}].display[{j}]「{line}」に英字または%記号あり。"
                        "登録済みの英語ツール名・AI関連語以外はカタカナ・日本語表記にすること"
                    )
        tts = cue.get("tts_text", "")
        if not isinstance(tts, str) or len(tts.strip()) < 3:
            errs.append(f"cue[{i}].tts_text が短すぎる")
        elif _speech_unstable_text(tts):
            errs.append(
                f"cue[{i}].tts_text に英字または%記号あり。ChatGPT以外はカタカナ・日本語表記にすること"
            )
        kana = cue.get("reading_kana", "")
        if not isinstance(kana, str) or len(kana.strip()) < 3:
            errs.append(f"cue[{i}].reading_kana が空または短すぎる")
        elif not _KANA_RE.match(kana.strip()):
            bad = "".join(sorted({c for c in kana if not _KANA_RE.match(c)}))[:10]
            errs.append(f"cue[{i}].reading_kana に非カタカナ文字あり（{bad}）。全てカタカナにすること")
        total_kana += len(kana)
        # 字幕表示内容が読み上げ文に実際に含まれるか（音韻ベースLCS包含チェック）
        if isinstance(disp, list) and isinstance(tts, str) and tts.strip():
            disp_norm = phonetic_hira("".join(disp))
            if disp_norm and lcs_coverage(disp_norm, phonetic_hira(tts)) < 0.70:
                errs.append(
                    f"cue[{i}] の字幕「{''.join(disp)}」に読み上げ文「{tts}」で話していない内容がある。"
                    "字幕は読み上げ文と同じ内容にすること"
                )

    if not (230 <= total_kana <= 480):
        errs.append(
            f"reading_kana 合計が{total_kana}文字。280〜400文字（許容230〜480）に収めること"
        )

    cap = data["caption"]
    if not isinstance(cap, str) or not (60 <= len(cap) <= 350):
        errs.append("caption は60〜350文字にすること")
    tags = data["hashtags"]
    if not isinstance(tags, list) or not (3 <= len(tags) <= 10) or not all(
        isinstance(t, str) and t.startswith("#") for t in tags
    ):
        errs.append("hashtags は #始まりの文字列3〜10個にすること")
    kws = data["card_keywords"]
    if not isinstance(kws, list) or len(kws) < image_count:
        errs.append(f"card_keywords は{image_count}個以上にすること")
    else:
        for k in kws[:image_count]:
            if not isinstance(k, str) or _char_width(k) > 12:
                errs.append(f"card_keyword「{k}」は12文字以内にすること")
    return errs


def _cue_signature(data: dict) -> str:
    parts: list[str] = []
    for cue in data.get("cues") or []:
        if not isinstance(cue, dict):
            continue
        display = cue.get("display")
        if isinstance(display, list):
            parts.extend(str(line) for line in display)
        parts.append(str(cue.get("tts_text") or ""))
        parts.append(str(cue.get("reading_kana") or ""))
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", "\n".join(parts))).lower()


def _recent_output_scripts(limit: int = 50) -> list[dict]:
    # Drive上のoutputsを直接走査するとFile Providerのロックで生成が止まりやすい。
    # 生成時の重複検知はruntimeローカルのwork履歴を正とする。
    try:
        paths = sorted(
            (p for p in CONFIG.work_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return []
    scripts: list[dict] = []
    for out_dir in paths[:limit]:
        script_path = out_dir / "script.json"
        try:
            scripts.append(json.loads(script_path.read_text(encoding="utf-8")))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return scripts


def recent_duplicate_errors(data: dict) -> list[str]:
    """Reject scripts that would recreate a recent video."""
    errs: list[str] = []
    title = str(data.get("title") or "").strip()
    if title:
        recent_titles = {
            unicodedata.normalize("NFKC", t).strip()
            for t in topic_store.recent_titles(50)
        }
        if unicodedata.normalize("NFKC", title).strip() in recent_titles:
            errs.append(f"title「{title}」は最近使用済み。別タイトル・別切り口にすること")

    signature = _cue_signature(data)
    if not signature:
        return errs
    for old in _recent_output_scripts(50):
        if signature == _cue_signature(old):
            old_title = old.get("title") or "無題"
            old_topic = old.get("topic") or ""
            errs.append(
                f"字幕/読み上げキューが過去動画「{old_title}」と同一。"
                f"別構成にすること（過去topic: {old_topic}）"
            )
            break
    return errs


def _extract_json(text: str) -> dict:
    """LLM出力からJSONを頑健に抽出する。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


DIFFICULTY_GUIDANCE = {
    "beginner": (
        "初心者向け。専門用語を避け、今日すぐ1回試せる単純な使い方に絞る。"
        "前提知識は置かず、手順は3ステップ以内にする。"
    ),
    "intermediate": (
        "中級者向け。単なる便利ワザではなく、実務ワークフロー化・品質チェック・失敗例・"
        "判断基準・テンプレ運用を中心にする。プロンプト文の紹介だけで終わらせず、"
        "入力設計、検証、改善ループ、チーム運用のどれかを必ず入れる。"
    ),
}

VALID_TARGET_PLATFORMS = {"common", "x", "instagram", "tiktok", "youtube"}

PLATFORM_GUIDANCE = {
    "common": (
        "共通動画向け。4媒体すべてで違和感が出ないよう、業務課題・判断基準・"
        "次に試す1アクションを中心にする。"
    ),
    "x": (
        "X向け。逆張り・問題提起・短い判断軸を強める。"
        "経営者やAI感度の高い実務家が返信・引用したくなる見解を入れる。"
    ),
    "instagram": (
        "Instagram向け。保存版・チェックリスト・3ステップを強める。"
        "後で見返せる実務テンプレとして成立させる。"
    ),
    "tiktok": (
        "TikTok向け。驚き・実演・あるあるを強める。"
        "難しいAI導入論を短く見せ、テンポを落とさない。"
    ),
    "youtube": (
        "YouTube Shorts向け。検索意図に合うHow-to・ツール比較・使い分けを強める。"
        "タイトルと内容を一致させ、長期で見られる解説にする。"
    ),
}


def normalize_target_platform(value: str | None) -> str:
    if not value:
        return "common"
    value = value.strip().lower()
    return value if value in VALID_TARGET_PLATFORMS else "common"


def _topic_text(topic: str | dict) -> str:
    if isinstance(topic, dict):
        return str(topic.get("topic") or "").strip()
    return str(topic or "").strip()


def _topic_meta(topic: str | dict) -> dict:
    if isinstance(topic, dict):
        return {k: v for k, v in topic.items() if v not in (None, "", [])}
    return {"topic": _topic_text(topic)}


def _list_text(value) -> str:
    if isinstance(value, list):
        return "、".join(str(v) for v in value if str(v).strip())
    return str(value or "").strip()


def _topic_context(meta: dict) -> str:
    lines: list[str] = []
    fields = [
        ("domain", "カテゴリ"),
        ("business_function", "業務領域"),
        ("primary_tools", "主なAIツール"),
        ("expertise_angle", "専門家視点"),
        ("target_persona", "想定視聴者"),
        ("avoid_angles", "避ける切り口"),
    ]
    for key, label in fields:
        value = _list_text(meta.get(key))
        if value:
            lines.append(f"- {label}: {value}")
    platform_angles = meta.get("platform_angles")
    if isinstance(platform_angles, dict) and platform_angles:
        lines.append("- SNS別の切り口:")
        for platform in ("x", "instagram", "tiktok", "youtube"):
            angle = str(platform_angles.get(platform) or "").strip()
            if angle:
                lines.append(f"  - {platform}: {angle}")
    return "\n".join(lines) if lines else "（追加メタ情報なし）"


def _build_prompt(
    topic: str | dict,
    image_count: int,
    difficulty: str = "beginner",
    target_platform: str = "common",
) -> str:
    prompt_path = CONFIG.prompts_dir / "script_prompt.md"
    try:
        tpl = retry_io(
            lambda: prompt_path.read_text(encoding="utf-8"),
            attempts=8,
            delay_sec=3.0,
        )
    except OSError as exc:
        if not is_transient_io_error(exc):
            raise
        local_prompt = Path(__file__).resolve().parents[1] / "prompts" / "script_prompt.md"
        tpl = retry_io(
            lambda: local_prompt.read_text(encoding="utf-8"),
            attempts=3,
            delay_sec=1.0,
        )
    recent = topic_store.recent_titles(30)
    recent_str = "\n".join(f"- {t}" for t in recent) if recent else "（まだ無し）"
    difficulty = topic_store.normalize_difficulty(difficulty) or "beginner"
    target_platform = normalize_target_platform(target_platform)
    meta = _topic_meta(topic)
    topic_text = _topic_text(topic)
    return (
        tpl.replace("{topic}", topic_text)
        .replace("{difficulty}", difficulty)
        .replace("{difficulty_guidance}", DIFFICULTY_GUIDANCE[difficulty])
        .replace("{target_platform}", target_platform)
        .replace("{platform_guidance}", PLATFORM_GUIDANCE[target_platform])
        .replace("{topic_context}", _topic_context(meta))
        .replace("{image_count}", str(image_count))
        .replace("{recent_titles}", recent_str)
    )


def _call_claude_cli(prompt: str) -> str:
    bin_path = CONFIG.get("llm", "claude_bin")
    model = CONFIG.get("llm", "claude_model") or None
    cmd = [bin_path, "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    env = os.environ.copy()
    path_parts = []
    nvm_root = Path.home() / ".nvm" / "versions" / "node"
    if nvm_root.exists():
        path_parts.extend(str(p / "bin") for p in sorted(nvm_root.glob("v*"), reverse=True))
    path_parts.extend(["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local" / "bin")])
    path_parts.append(env.get("PATH", ""))
    env["PATH"] = ":".join(p for p in path_parts if p)
    # cwd はランタイムディレクトリ（プロジェクトのCLAUDE.md等を読み込ませない）
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CONFIG.get("llm", "timeout_sec", default=300),
        cwd=str(CONFIG.runtime_dir),
        env=env,
    )
    if proc.returncode != 0:
        detail = proc.stderr[:500]
        if not detail.strip() and proc.stdout:
            try:
                detail = str(json.loads(proc.stdout).get("result") or proc.stdout[:500])
            except json.JSONDecodeError:
                detail = proc.stdout[:500]
        raise RuntimeError(f"claude CLI failed rc={proc.returncode}: {detail}")
    wrapper = json.loads(proc.stdout)
    result = wrapper.get("result")
    if not result:
        raise RuntimeError(f"claude CLI empty result: {proc.stdout[:300]}")
    return result


def _call_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=CONFIG.openai_api_key)
    resp = client.chat.completions.create(
        model=CONFIG.get("llm", "openai_model", default="gpt-5.1"),
        messages=[
            {"role": "system", "content": "JSONのみを出力する日本語放送作家。"},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _fallback_cues_for_topic(topic: str) -> tuple[str, list[dict]]:
    if "営業メール" in topic:
        return "営業メール改善の手順", [
            {
                "display": ["返信ゼロの原因", "そこじゃないかも"],
                "tts_text": "返信ゼロの原因、そこじゃないかもしれません。",
                "reading_kana": "ヘンシンゼロノゲンイン、ソコジャナイカモシレマセン。",
                "emphasis": True,
            },
            {
                "display": ["中級者はまず", "数字で見ます"],
                "tts_text": "中級者は、まず反応を数字で見ます。",
                "reading_kana": "チュウキュウシャハ、マズハンノウヲスウジデミマス。",
                "emphasis": True,
            },
            {
                "display": ["件名だけを", "一つ変えます"],
                "tts_text": "最初は、件名だけを一つ変えます。",
                "reading_kana": "サイショハ、ケンメイダケヲヒトツカエマス。",
                "emphasis": False,
            },
            {
                "display": ["本文冒頭は", "別で試します"],
                "tts_text": "本文の冒頭は、別の回で試します。",
                "reading_kana": "ホンブンノボウトウハ、ベツノカイデタメシマス。",
                "emphasis": False,
            },
            {
                "display": ["相手の役職を", "必ず入れる"],
                "tts_text": "相手の役職や悩みを、必ず入れます。",
                "reading_kana": "アイテノヤクショクヤナヤミヲ、カナラズイレマス。",
                "emphasis": False,
            },
            {
                "display": ["誰に何を頼むか", "明確にします"],
                "tts_text": "誰に何を頼むメールなのか、明確にします。",
                "reading_kana": "ダレニナニヲタノムメールナノカ、メイカクニシマス。",
                "emphasis": False,
            },
            {
                "display": ["送った数と返信を", "表に残します"],
                "tts_text": "送った数と返信数を、表に残します。",
                "reading_kana": "オクッタカズトヘンシンスウヲ、ヒョウニノコシマス。",
                "emphasis": True,
            },
            {
                "display": ["勝った文だけ", "残します"],
                "tts_text": "反応がよかった文だけを残します。",
                "reading_kana": "ハンノウガヨカッタブンダケヲノコシマス。",
                "emphasis": False,
            },
            {
                "display": ["次は違う要素を", "一つ試します"],
                "tts_text": "次は違う要素を、一つだけ試します。",
                "reading_kana": "ツギハチガウヨウソヲ、ヒトツダケタメシマス。",
                "emphasis": False,
            },
            {
                "display": ["全部変えると", "理由が消えます"],
                "tts_text": "全部を一気に変えると、理由が分からなくなります。",
                "reading_kana": "ゼンブヲイッキニカエルト、リユウガワカラナクナリマス。",
                "emphasis": True,
            },
            {
                "display": ["良い文面を", "共有します"],
                "tts_text": "反応がよかった文面は、チームで共有します。",
                "reading_kana": "ハンノウガヨカッタブンメンハ、チームデキョウユウシマス。",
                "emphasis": False,
            },
            {
                "display": ["毎週見直して", "文面を育てます"],
                "tts_text": "毎週見直して、文面を育てます。",
                "reading_kana": "マイシュウミナオシテ、ブンメンヲソダテマス。",
                "emphasis": False,
            },
            {
                "display": ["保存して次の", "メールで試して"],
                "tts_text": "保存して、次の営業メールで試してください。",
                "reading_kana": "ホゾンシテ、ツギノエイギョウメールデタメシテクダサイ。",
                "emphasis": False,
            },
        ]
    if "業務フロー" in topic or "自動化候補" in topic:
        return "自動化候補を見抜く3軸", [
            {
                "display": ["自動化する仕事", "勘で選んでない？"],
                "tts_text": "自動化する仕事、勘で選んでいませんか。",
                "reading_kana": "ジドウカスルシゴト、カンデエランデイマセンカ。",
                "emphasis": True,
            },
            {
                "display": ["見るのは", "三つだけです"],
                "tts_text": "見るのは、頻度、時間、ルール化の三つです。",
                "reading_kana": "ミルノハ、ヒンド、ジカン、ルールカノミッツデス。",
                "emphasis": True,
            },
            {
                "display": ["毎日ある作業を", "先に出します"],
                "tts_text": "まず毎日発生する作業を、先に書き出します。",
                "reading_kana": "マズマイニチハッセイスルサギョウヲ、サキニカキダシマス。",
                "emphasis": False,
            },
            {
                "display": ["一回の時間を", "横に書きます"],
                "tts_text": "次に、一回あたりの時間を横に書きます。",
                "reading_kana": "ツギニ、イッカイアタリノジカンヲヨコニカキマス。",
                "emphasis": False,
            },
            {
                "display": ["判断が単純なら", "候補です"],
                "tts_text": "判断が単純な作業ほど、最初の候補になります。",
                "reading_kana": "ハンダンガタンジュンナサギョウホド、サイショノコウホニナリマス。",
                "emphasis": True,
            },
            {
                "display": ["人の確認が多い", "仕事は後回し"],
                "tts_text": "人の確認が多い仕事は、後回しにします。",
                "reading_kana": "ヒトノカクニンガオオイシゴトハ、アトマワシニシマス。",
                "emphasis": False,
            },
            {
                "display": ["一週間だけ", "試します"],
                "tts_text": "候補を一つ選んだら、一週間だけ試します。",
                "reading_kana": "コウホヲヒトツエランダラ、イッシュウカンダケタメシマス。",
                "emphasis": False,
            },
            {
                "display": ["減った時間を", "数字で見ます"],
                "tts_text": "最後に、減った時間を数字で確認します。",
                "reading_kana": "サイゴニ、ヘッタジカンヲスウジデカクニンシマス。",
                "emphasis": False,
            },
            {
                "display": ["保存して次の", "棚卸しに使って"],
                "tts_text": "保存して、次の業務棚卸しで試してください。",
                "reading_kana": "ホゾンシテ、ツギノギョウムタナオロシデタメシテクダサイ。",
                "emphasis": False,
            },
        ]
    if "採用面接" in topic or "評価基準" in topic:
        return "面接評価をそろえる3基準", [
            {
                "display": ["面接評価", "人でズレてない？"],
                "tts_text": "面接評価、人によってズレていませんか。",
                "reading_kana": "メンセツヒョウカ、ヒトニヨッテズレテイマセンカ。",
                "emphasis": True,
            },
            {
                "display": ["質問を増やす前に", "基準をそろえる"],
                "tts_text": "質問を増やす前に、評価基準をそろえます。",
                "reading_kana": "シツモンヲフヤスマエニ、ヒョウカキジュンヲソロエマス。",
                "emphasis": True,
            },
            {
                "display": ["任せる仕事を", "三つ書きます"],
                "tts_text": "まず任せたい仕事を、三つだけ書きます。",
                "reading_kana": "マズマカセタイシゴトヲ、ミッツダケカキマス。",
                "emphasis": False,
            },
            {
                "display": ["必要な行動を", "言葉にします"],
                "tts_text": "次に、その仕事で必要な行動を言葉にします。",
                "reading_kana": "ツギニ、ソノシゴトデヒツヨウナコウドウヲコトバニシマス。",
                "emphasis": False,
            },
            {
                "display": ["五段階ではなく", "具体例で見る"],
                "tts_text": "五段階だけでなく、具体例で評価します。",
                "reading_kana": "ゴダンカイダケデナク、グタイレイデヒョウカシマス。",
                "emphasis": True,
            },
            {
                "display": ["発言の引用を", "一つ残します"],
                "tts_text": "候補者の発言は、引用として一つ残します。",
                "reading_kana": "コウホシャノハツゲンハ、インヨウトシテヒトツノコシマス。",
                "emphasis": False,
            },
            {
                "display": ["面接後すぐ", "根拠を書く"],
                "tts_text": "面接後すぐ、判断の根拠を書き残します。",
                "reading_kana": "メンセツゴスグ、ハンダンノコンキョヲカキノコシマス。",
                "emphasis": False,
            },
            {
                "display": ["評価者同士で", "ズレを見ます"],
                "tts_text": "評価者同士で、点数がズレた理由を見ます。",
                "reading_kana": "ヒョウカシャドウシデ、テンスウガズレタリユウヲミマス。",
                "emphasis": False,
            },
            {
                "display": ["迷った項目は", "保留にします"],
                "tts_text": "迷った項目は、その場で決めず保留にします。",
                "reading_kana": "マヨッタコウモクハ、ソノバデキメズホリュウニシマス。",
                "emphasis": False,
            },
            {
                "display": ["保存して次の", "面接で試して"],
                "tts_text": "保存して、次の面接準備で試してください。",
                "reading_kana": "ホゾンシテ、ツギノメンセツジュンビデタメシテクダサイ。",
                "emphasis": False,
            },
        ]
    if "競合比較" in topic or "差別化" in topic:
        return "競合比較で差が出る3視点", [
            {
                "display": ["競合比較", "表で終わってない？"],
                "tts_text": "競合比較、表で終わっていませんか。",
                "reading_kana": "キョウゴウヒカク、ヒョウデオワッテイマセンカ。",
                "emphasis": True,
            },
            {
                "display": ["見るべきは", "差の理由です"],
                "tts_text": "見るべきは、違いそのものではなく差の理由です。",
                "reading_kana": "ミルベキハ、チガイソノモノデハナクサノリユウデス。",
                "emphasis": True,
            },
            {
                "display": ["価格と機能を", "まず並べます"],
                "tts_text": "まず価格と機能を、横並びにします。",
                "reading_kana": "マズカカクトキノウヲ、ヨコナラビニシマス。",
                "emphasis": False,
            },
            {
                "display": ["次に顧客の", "不満を足します"],
                "tts_text": "次に、顧客が不満に思う点を足します。",
                "reading_kana": "ツギニ、コキャクガフマンニオモウテンヲタシマス。",
                "emphasis": False,
            },
            {
                "display": ["勝ち負けより", "選ばれる条件"],
                "tts_text": "勝ち負けより、選ばれる条件を見ます。",
                "reading_kana": "カチマケヨリ、エラバレルジョウケンヲミマス。",
                "emphasis": False,
            },
            {
                "display": ["自社が勝てる", "場面を探す"],
                "tts_text": "最後に、自社が勝てる場面を探します。",
                "reading_kana": "サイゴニ、ジシャガカテルバメンヲサガシマス。",
                "emphasis": True,
            },
            {
                "display": ["弱い項目は", "補う策を考える"],
                "tts_text": "弱い項目は、補う策を考えます。",
                "reading_kana": "ヨワイコウモクハ、オギナウサクヲカンガエマス。",
                "emphasis": False,
            },
            {
                "display": ["選ばれにくい", "理由も書く"],
                "tts_text": "選ばれにくい理由も、一行で書きます。",
                "reading_kana": "エラバレニクイリユウモ、イチギョウデカキマス。",
                "emphasis": False,
            },
            {
                "display": ["顧客別に", "結論を分ける"],
                "tts_text": "顧客の状況別に、結論を分けます。",
                "reading_kana": "コキャクノジョウキョウベツニ、ケツロンヲワケマス。",
                "emphasis": False,
            },
            {
                "display": ["保存して次の", "提案に使って"],
                "tts_text": "保存して、次の提案準備で試してください。",
                "reading_kana": "ホゾンシテ、ツギノテイアンジュンビデタメシテクダサイ。",
                "emphasis": False,
            },
        ]
    return "仕事で使える改善手順", [
        {
            "display": ["その依頼", "時間をムダに"],
            "tts_text": "その依頼、時間をムダにしているかもしれません。",
            "reading_kana": "ソノイライ、ジカンヲムダニシテイルカモシレマセン。",
            "emphasis": True,
        },
        {
            "display": ["原因は", "前提が足りない"],
            "tts_text": "原因は、最初の前提が足りないことです。",
            "reading_kana": "ゲンインハ、サイショノゼンテイガタリナイコトデス。",
            "emphasis": True,
        },
        {
            "display": ["目的と相手と", "制約を書きます"],
            "tts_text": "目的と相手と制約を、先に書きます。",
            "reading_kana": "モクテキトアイテトセイヤクヲ、サキニカキマス。",
            "emphasis": False,
        },
        {
            "display": ["出力形式も", "先に指定します"],
            "tts_text": "出力形式も、先に指定します。",
            "reading_kana": "シュツリョクケイシキモ、サキニシテイシマス。",
            "emphasis": False,
        },
        {
            "display": ["一回で決めず", "二案を並べます"],
            "tts_text": "一回で決めず、二案を並べます。",
            "reading_kana": "イッカイデキメズ、ニアンヲナラベマス。",
            "emphasis": False,
        },
        {
            "display": ["良い案だけを", "残して比べます"],
            "tts_text": "良い案だけを残して、比べます。",
            "reading_kana": "ヨイアンダケヲノコシテ、クラベマス。",
            "emphasis": False,
        },
        {
            "display": ["数字や事例で", "根拠を足します"],
            "tts_text": "数字や事例で、根拠を足します。",
            "reading_kana": "スウジヤジレイデ、コンキョヲタシマス。",
            "emphasis": True,
        },
        {
            "display": ["最後に弱点を", "自分で聞きます"],
            "tts_text": "最後に弱点を、自分で聞きます。",
            "reading_kana": "サイゴニジャクテンヲ、ジブンデキキマス。",
            "emphasis": False,
        },
        {
            "display": ["その反論まで", "直して完成"],
            "tts_text": "その反論まで直して、完成です。",
            "reading_kana": "ソノハンロンマデナオシテ、カンセイデス。",
            "emphasis": False,
        },
        {
            "display": ["使えた指示を", "保存します"],
            "tts_text": "使えた指示だけを、次回用に保存します。",
            "reading_kana": "ツカエタシジダケヲ、ジカイヨウニホゾンシマス。",
            "emphasis": False,
        },
        {
            "display": ["チームなら", "共有します"],
            "tts_text": "チームで使うなら、共有します。",
            "reading_kana": "チームデツカウナラ、キョウユウシマス。",
            "emphasis": False,
        },
        {
            "display": ["迷ったら", "前提を見直す"],
            "tts_text": "迷ったら、目的と制約を見直すと安定します。",
            "reading_kana": "マヨッタラ、モクテキトセイヤクヲミナオストアンテイシマス。",
            "emphasis": True,
        },
        {
            "display": ["保存して次の", "仕事で試して"],
            "tts_text": "保存して、次の仕事で試してください。",
            "reading_kana": "ホゾンシテ、ツギノシゴトデタメシテクダサイ。",
            "emphasis": False,
        },
    ]


def _fallback_script(
    topic: str | dict,
    difficulty: str,
    last_errs: list[str],
    target_platform: str = "common",
) -> dict:
    meta = _topic_meta(topic)
    topic_text = _topic_text(topic)
    title, cues = _fallback_cues_for_topic(topic_text)
    return {
        "title": title,
        "cues": cues,
        "caption": (
            f"{topic_text}の実務向けショートです。"
            "一回で当てにいくより、前提をそろえて記録しながら改善する方が安定します。"
            "保存して、次の仕事でそのまま試してみてください。"
        ),
        "hashtags": ["#生成AI", "#AI活用", "#AI導入", "#仕事術", "#業務効率化"],
        "card_keywords": ["前提整理", "記録", "改善", "共有"],
        "topic": topic_text,
        "difficulty": difficulty,
        "target_platform": normalize_target_platform(target_platform),
        "content_strategy": {
            key: meta[key]
            for key in ("domain", "business_function", "primary_tools", "expertise_angle", "target_persona")
            if key in meta
        },
        "platform_angles": meta.get("platform_angles", {}),
        "fallback_reason": "; ".join(last_errs[:3]),
    }


def generate_script(topic: str | dict, difficulty: str = "beginner", target_platform: str = "common") -> dict:
    """テーマから検証済み台本JSONを生成する。"""
    image_count = int(CONFIG.get("images", "count", default=4))
    provider = CONFIG.get("llm", "provider", default="claude_cli")
    if provider == "openai" and not CONFIG.openai_api_key:
        provider = "claude_cli"

    difficulty = topic_store.normalize_difficulty(difficulty) or "beginner"
    target_platform = normalize_target_platform(target_platform)
    topic_text = _topic_text(topic)
    meta = _topic_meta(topic)
    prompt = _build_prompt(topic, image_count, difficulty, target_platform)
    retries = int(CONFIG.get("llm", "retries", default=3))
    last_errs: list[str] = []
    for attempt in range(1, retries + 1):
        full_prompt = prompt
        if last_errs:
            full_prompt += (
                "\n\n## 前回出力の問題点（必ず修正すること）\n"
                + "\n".join(f"- {e}" for e in last_errs)
            )
        try:
            raw = _call_openai(full_prompt) if provider == "openai" else _call_claude_cli(full_prompt)
        except subprocess.TimeoutExpired:
            last_errs = [
                f"{provider} が {CONFIG.get('llm', 'timeout_sec', default=300)} 秒でタイムアウト。"
                "同じ条件で再試行すること"
            ]
            continue
        except RuntimeError as e:
            last_errs = [str(e)]
            continue
        try:
            data = normalize_generated_script(_extract_json(raw))
        except (json.JSONDecodeError, ValueError) as e:
            last_errs = [f"JSONとしてパース不能: {e}"]
            continue
        errs = validate_script(data, image_count)
        if not errs:
            errs = recent_duplicate_errors(data)
        if not errs:
            data["topic"] = topic_text
            data["difficulty"] = difficulty
            data["target_platform"] = target_platform
            data["content_strategy"] = {
                key: meta[key]
                for key in ("domain", "business_function", "primary_tools", "expertise_angle", "target_persona")
                if key in meta
            }
            data["platform_angles"] = meta.get("platform_angles", {})
            return data
        last_errs = errs
    data = _fallback_script(topic, difficulty, last_errs, target_platform)
    errs = validate_script(data, image_count)
    if not errs:
        errs = recent_duplicate_errors(data)
    if not errs:
        return data
    raise RuntimeError(
        f"台本生成が{retries}回失敗し、フォールバック台本も不合格。最終エラー: "
        + "; ".join((last_errs + errs)[:5])
    )


# ===================== Seedance版（AI動画背景・ネイティブ音声） =====================
#
# 通常版と違い、VOICEVOXナレーションを使わず、Seedance 2.0が生成する動画に
# ネイティブ音声（日本語セリフ）が含まれる。そのため台本は
# 「カットごとの英語video_prompt + 日本語セリフ(tts_text) + カタカナ読み(tts_kana)」
# の形を取る。
#
# 読み分離方式（オーナーフィードバック対応）:
# Seedanceにtts_text（漢字仮名交じり）をそのまま読ませると、音読み/訓読みの
# 誤読が発生する（例:「一昨日」「上手」等の複数読みを持つ語）。VOICEVOX版と
# 同様に「読み上げはカタカナ読み仮名・テロップは漢字表記」を分離し、
# Seedanceには tts_kana（正確なカタカナ読み）だけを発話させる。
# tts_text は字幕表示・CER検証（whisper突合）の基準として引き続き使う。
#
# セリフ注入方式（重要・実E2Eで発覚した不具合の修正）:
# 当初はLLMにvideo_prompt内へ直接セリフを埋め込ませ、tts_textとの完全一致を
# 検証していたが、LLMは引用符・空白・句読点をわずかに変形するため機械検証が
# 構造的に通らなかった。そこでLLMには `{{LINE}}` というプレースホルダーだけを
# 書かせ、後処理（inject_tts_line_into_prompt）でtts_kana原文を機械的に
# 置換する方式にした。これにより「プロンプト内セリフ=発話させたいカタカナ読み」が
# 常に構造的に保証され、完全一致検証そのものが不要になる。

SEEDANCE_SCHEMA_KEYS = {
    "title", "character_description", "room_description", "camera_description",
    "cues", "caption", "hashtags", "card_keywords",
}

LINE_PLACEHOLDER = "{{LINE}}"
SEEDANCE_FIXED_CHARACTER_DESCRIPTION = (
    "A 45-year-old Japanese male business professional, medium complexion, calm sharp eyes, "
    "slightly long rectangular face, short neatly side-parted black hair with slight gray "
    "at the temples, clean-shaven, wearing a dark navy business suit, crisp white shirt, "
    "and dark solid tie, capable and calm executive consultant vibe"
)
SEEDANCE_FIXED_ROOM_DESCRIPTION = (
    "A modern Japanese office meeting room with neutral white walls, glass partition, "
    "tidy desk, soft natural daylight, no distracting props"
)
SEEDANCE_FIXED_CAMERA_DESCRIPTION = (
    "Vertical 9:16 video, bust-up framing, camera at eye level, direct eye contact, "
    "professional talking-head style, locked-off camera, no zoom, no push-in, no close-up change"
)
_SEEDANCE_FEMALE_TERMS_RE = re.compile(r"\b(woman|female|girl|she|her)\b", re.IGNORECASE)

# tts_kana に許容する文字種（VOICEVOX版のreading_kana検証 _KANA_RE と同じ基準）。
_SEEDANCE_KANA_RE = _KANA_RE

# tts_textとtts_kanaの読み整合チェックの許容CER。
# pykakasiの漢字→ひらがな変換は完全ではない（複合語・固有名詞等でずれる）ため、
# VOICEVOX側のreading_kana突合（kana_mismatch_cer=0.15）よりやや緩める。
SEEDANCE_KANA_MISMATCH_CER_MAX = 0.35


def inject_tts_line_into_prompt(video_prompt: str, tts_kana: str) -> str:
    """video_prompt内のプレースホルダーをtts_kana（カタカナ読み）原文へ機械的に置換する。

    Seedanceには漢字仮名交じりのtts_textではなく、カタカナ読みのtts_kanaを
    発話させることで、音読み/訓読みの誤読を防ぐ（VOICEVOX版のreading_kana
    直読みフォールバックと同じ発想）。

    LLMが `{{LINE}}` を書き忘れた場合や、既にセリフ風の文字列を書いてしまった
    場合でも、必ずtts_kana原文が1箇所だけ含まれるプロンプトを返す
    （末尾に `He says in Japanese: "<tts_kana>"` を追記するフォールバック）。
    """
    quoted = f'says in Japanese: "{tts_kana}"'
    if LINE_PLACEHOLDER in video_prompt:
        return video_prompt.replace(LINE_PLACEHOLDER, f'"{tts_kana}"')
    # プレースホルダーが無い場合は、確実にtts_kana原文が入るよう末尾に追記する。
    # LLMが独自にセリフを書いていても、検証・生成が依存するのはこの追記分だけ。
    prompt = video_prompt.rstrip()
    if not prompt.endswith((".", "!", "?", "。")):
        prompt += "."
    return f"{prompt} He {quoted}."


def _seedance_identity_errors(data: dict) -> list[str]:
    """Seedance版の話者・部屋・服装が固定条件を満たしているか検証する。"""
    errs: list[str] = []
    character = str(data.get("character_description", ""))
    room = str(data.get("room_description", ""))
    camera = str(data.get("camera_description", ""))
    identity_text = " ".join([character, room, camera]).lower()
    required_character_terms = {
        "45-year-old": ["45-year-old", "45 year old", "45"],
        "male": ["male", "man"],
        "business professional": ["business professional", "businessman", "executive consultant"],
        "dark navy suit": ["navy", "suit"],
        "white shirt": ["white shirt"],
        "tie": ["tie"],
    }
    for label, aliases in required_character_terms.items():
        if not any(alias in identity_text for alias in aliases):
            errs.append(f"Seedance話者設定に {label} が含まれていません")
    if _SEEDANCE_FEMALE_TERMS_RE.search(identity_text):
        errs.append("Seedance話者設定に女性を示す語が含まれています")

    required_room_terms = ("office", "meeting room")
    if not all(term in room.lower() for term in required_room_terms):
        errs.append("Seedance背景はmodern Japanese office meeting roomに固定してください")
    if "bust-up" not in camera.lower() and "upper-body" not in camera.lower():
        errs.append("Seedanceカメラはbust-up/upper-body framingに固定してください")
    if "locked-off" not in camera.lower() or "no zoom" not in camera.lower():
        errs.append("Seedanceカメラはlocked-off camera / no zoomに固定してください")

    for i, cue in enumerate(data.get("cues", [])):
        if not isinstance(cue, dict):
            continue
        prompt = str(cue.get("video_prompt", ""))
        lower_prompt = prompt.lower()
        if _SEEDANCE_FEMALE_TERMS_RE.search(lower_prompt):
            errs.append(f"cue[{i}].video_prompt に女性を示す語が含まれています")
        if "45" not in lower_prompt or not any(term in lower_prompt for term in ("male", "man")):
            errs.append(f"cue[{i}].video_prompt に固定条件 45-year-old male が不足しています")
        prompt_required = {
            "navy suit": ["navy", "suit"],
            "white shirt": ["white shirt"],
            "tie": ["tie"],
            "office meeting room": ["office", "meeting room"],
            "locked camera": ["locked-off", "no zoom"],
        }
        for label, aliases in prompt_required.items():
            if not all(alias in lower_prompt for alias in aliases):
                errs.append(f"cue[{i}].video_prompt に固定条件 {label} が不足しています")
        if i > 0 and "same" not in lower_prompt:
            errs.append(f"cue[{i}].video_prompt に前カットと同一人物・同一環境を示す same が不足しています")
    return errs


def _build_seedance_prompt(topic: str | dict, difficulty: str, cut_count: int) -> str:
    prompt_path = CONFIG.prompts_dir / "seedance_script_prompt.md"
    try:
        tpl = retry_io(
            lambda: prompt_path.read_text(encoding="utf-8"),
            attempts=8,
            delay_sec=3.0,
        )
    except OSError as exc:
        if not is_transient_io_error(exc):
            raise
        local_prompt = Path(__file__).resolve().parents[1] / "prompts" / "seedance_script_prompt.md"
        tpl = retry_io(
            lambda: local_prompt.read_text(encoding="utf-8"),
            attempts=3,
            delay_sec=1.0,
        )
    recent = topic_store.recent_titles(30)
    recent_str = "\n".join(f"- {t}" for t in recent) if recent else "（まだ無し）"
    difficulty = topic_store.normalize_difficulty(difficulty) or "beginner"
    topic_text = _topic_text(topic)
    return (
        tpl.replace("{topic}", topic_text)
        .replace("{difficulty}", difficulty)
        .replace("{difficulty_guidance}", DIFFICULTY_GUIDANCE[difficulty])
        .replace("{cut_count}", str(cut_count))
        .replace("{recent_titles}", recent_str)
    )


def validate_seedance_script(data: dict, cut_count: int) -> list[str]:
    """Seedance版台本JSONの機械検証。問題点のリストを返す（空なら合格）。"""
    errs: list[str] = []
    if not isinstance(data, dict):
        return ["JSONオブジェクトではない"]
    missing = SEEDANCE_SCHEMA_KEYS - set(data)
    if missing:
        errs.append(f"必須キー欠落: {sorted(missing)}")
        return errs

    title = data["title"]
    if not isinstance(title, str) or not (4 <= len(title) <= 32):
        errs.append("title は4〜32文字の文字列にすること")

    for key in ("character_description", "room_description", "camera_description"):
        if not isinstance(data.get(key), str) or len(data[key].strip()) < 10:
            errs.append(f"{key} は具体的な英語説明にすること（10文字以上）")

    errs.extend(_seedance_identity_errors(data))

    cues = data["cues"]
    if not isinstance(cues, list) or len(cues) != cut_count:
        errs.append(f"cues は{cut_count}個ちょうどにすること（現在 {len(cues) if isinstance(cues, list) else '不正'}）")
        return errs

    max_line = CONFIG.get("subtitle", "max_chars_per_line", default=13)
    for i, cue in enumerate(cues):
        if not isinstance(cue, dict):
            errs.append(f"cue[{i}] がオブジェクトでない")
            continue
        vp = cue.get("video_prompt", "")
        if not isinstance(vp, str) or len(vp.strip()) < 20:
            errs.append(f"cue[{i}].video_prompt が短すぎる（20文字以上の英語プロンプトにすること）")
        tts = cue.get("tts_text", "")
        if not isinstance(tts, str) or not (10 <= len(tts.strip()) <= 90):
            errs.append(f"cue[{i}].tts_text は10〜90文字にすること（現在 {len(tts.strip()) if isinstance(tts, str) else 0}）")
        # 注意: video_prompt内にtts_text（漢字仮名交じり）と同一の文字列が
        # 含まれるかの完全一致検証は行わない。LLMは引用符・空白・句読点を
        # わずかに変形するため構造的に通らないことが実E2Eで判明したため撤廃した。
        # セリフの注入は inject_tts_line_into_prompt() が機械的に保証する
        # （プレースホルダー置換 or 末尾追記のフォールバック）。
        kana = cue.get("tts_kana", "")
        if not isinstance(kana, str) or len(kana.strip()) < 3:
            errs.append(f"cue[{i}].tts_kana が空または短すぎる（漢字の誤読防止のため必須）")
        elif not _SEEDANCE_KANA_RE.match(kana.strip()):
            bad = "".join(sorted({c for c in kana if not _SEEDANCE_KANA_RE.match(c)}))[:10]
            errs.append(f"cue[{i}].tts_kana に非カタカナ文字あり（{bad}）。全てカタカナにすること")
        elif isinstance(tts, str) and tts.strip():
            # tts_text（漢字仮名交じり）とtts_kana（カタカナ読み）が同じ内容を
            # 指しているかを、両者を音韻正規化した上でCERで突合する。
            # pykakasiの自動読み（tts_text側）と人手相当の読み（tts_kana側）を
            # 比較するため、VOICEVOXのreading_kana突合よりCER許容を緩めている。
            mismatch = phonetic_cer(tts, kana)
            if mismatch > SEEDANCE_KANA_MISMATCH_CER_MAX:
                errs.append(
                    f"cue[{i}].tts_kana「{kana}」が tts_text「{tts}」と読みが一致しない"
                    f"（音韻CER={mismatch:.2f} > 上限{SEEDANCE_KANA_MISMATCH_CER_MAX}）。"
                    "tts_textの正確な読みをカタカナで書き直すこと"
                )
        disp = cue.get("display")
        if not isinstance(disp, list) or not (1 <= len(disp) <= 2):
            errs.append(f"cue[{i}].display は1〜2行の配列にすること")
        else:
            for j, line in enumerate(disp):
                if not isinstance(line, str) or not line.strip():
                    errs.append(f"cue[{i}].display[{j}] が空")
                elif _char_width(line) > max_line:
                    errs.append(
                        f"cue[{i}].display[{j}]「{line}」が{_char_width(line)}文字で上限{max_line}文字超過"
                    )

    cap = data["caption"]
    if not isinstance(cap, str) or not (60 <= len(cap) <= 350):
        errs.append("caption は60〜350文字にすること")
    tags = data["hashtags"]
    if not isinstance(tags, list) or not (3 <= len(tags) <= 10) or not all(
        isinstance(t, str) and t.startswith("#") for t in tags
    ):
        errs.append("hashtags は #始まりの文字列3〜10個にすること")
    kws = data["card_keywords"]
    if not isinstance(kws, list) or len(kws) < cut_count:
        errs.append(f"card_keywords は{cut_count}個以上にすること（フォールバック用）")
    return errs


def _apply_line_injection(data: dict) -> dict:
    """全cueのvideo_promptにtts_kana（カタカナ読み）を機械的に注入する（破壊的に
    見えるがdataを直接書き換える。呼び出し元は検証・返却の前に必ずこれを通すこと）。

    Seedanceにはtts_text（漢字仮名交じり）ではなくtts_kana（カタカナ読み）を
    発話させることで、漢字の音読み/訓読み誤読を防ぐ（オーナーフィードバック対応）。
    tts_kanaが欠落している異常データでは、注入をスキップせずtts_textにフォール
    バックする（validate_seedance_scriptで別途tts_kana必須エラーを検出する）。
    """
    for cue in data.get("cues", []):
        if not isinstance(cue, dict):
            continue
        vp = cue.get("video_prompt")
        kana = cue.get("tts_kana")
        tts = cue.get("tts_text")
        line_source = kana if isinstance(kana, str) and kana.strip() else tts
        if isinstance(vp, str) and isinstance(line_source, str):
            cue["video_prompt"] = inject_tts_line_into_prompt(vp, line_source)
    return data


def _fallback_seedance_script(topic: str | dict, difficulty: str, last_errs: list[str]) -> dict:
    """Seedance生成もLLM生成も失敗した場合の最終フォールバック台本。

    この場合でも呼び出し元（pipeline.py）は例外を検知して静止画版へ
    フォールバックする設計のため、ここでは軽量な汎用台本を返す。
    決定論的な固定文言のため、直近動画との重複チェック
    （recent_duplicate_errors）の対象からは意図的に除外する
    （非常用フォールバックにまで「ネタ被り禁止」を課すと、同一topicの
    2回目以降で必ず重複判定に引っかかり、フォールバックが機能しなくなるため）。
    """
    topic_text = _topic_text(topic)
    character = SEEDANCE_FIXED_CHARACTER_DESCRIPTION
    room = SEEDANCE_FIXED_ROOM_DESCRIPTION
    camera = SEEDANCE_FIXED_CAMERA_DESCRIPTION
    lines = [
        (
            "実は多くの人が知らない使い方があります。今日は3つだけ紹介しますね。",
            "ジツハオオクノヒトガシラナイツカイカタガアリマス。キョウハミッツダケショウカイシマスネ。",
            ["知らない使い方", "3つ紹介します"],
            True,
        ),
        (
            "1つ目は業務時間を記録して、無駄な作業を見える化することです。",
            "ヒトツメハギョウムジカンヲキロクシテ、ムダナサギョウヲミエルカスルコトデス。",
            ["業務時間を記録", "無駄を見える化"],
            False,
        ),
        (
            "2つ目は判断基準をチームで共有して、ばらつきを減らすことです。",
            "フタツメハハンダンキジュンヲチームデキョウユウシテ、バラツキヲヘラスコトデス。",
            ["判断基準を共有", "ばらつき減らす"],
            False,
        ),
        (
            "続きはプロフィールから見てくださいね。それではまた次回。",
            "ツヅキハプロフィールカラミテクダサイネ。ソレデハマタジカイ。",
            ["続きはプロフィールから"],
            False,
        ),
    ]
    cues = []
    for text, kana, disp, emph in lines:
        cues.append(
            {
                "video_prompt": (
                    f"{character}, sitting in the same {room}, same {camera}. "
                    f"He looks at the camera and says in Japanese: {LINE_PLACEHOLDER}"
                ),
                "tts_text": text,
                "tts_kana": kana,
                "display": disp,
                "emphasis": emph,
            }
        )
    data = {
        "title": f"{topic_text}の実務ポイント",
        "character_description": character,
        "room_description": room,
        "camera_description": camera,
        "cues": cues,
        "caption": (
            f"{topic_text}の実務向けショートです。"
            "前提をそろえて記録しながら改善すると安定します。"
            "続きはプロフィールから見てください。"
        ),
        "hashtags": ["#生成AI", "#AI活用", "#AI導入", "#仕事術", "#業務効率化"],
        "card_keywords": ["前提整理", "記録", "改善", "共有"],
        "topic": topic_text,
        "difficulty": difficulty,
        "target_platform": "common",
        "content_strategy": {},
        "platform_angles": {},
        "fallback_reason": "; ".join(last_errs[:3]),
        "is_fallback": True,
    }
    return _apply_line_injection(data)


def generate_seedance_script(topic: str | dict, difficulty: str = "beginner", cut_count: int = 4) -> dict:
    """Seedance版（AI動画背景・ネイティブ音声）台本を生成する。

    通常版 generate_script と同じ検証済み台本JSONを返すが、cues は
    display/tts_text に加えて video_prompt（Seedance用英語プロンプト）と
    tts_kana（tts_textの正確なカタカナ読み）を持つ。
    target_platform は常に common（共通動画モード）。

    video_prompt内のセリフは、LLMが書いた `{{LINE}}` プレースホルダー（または
    それに相当する箇所）を tts_kana（カタカナ読み）原文で機械的に置換して
    確定させる（inject_tts_line_into_prompt）。Seedanceには漢字仮名交じりの
    tts_textではなくtts_kanaを発話させることで、漢字の音読み/訓読み誤読を
    防ぐ（VOICEVOX版のreading_kana直読みフォールバックと同じ発想）。
    LLM出力の完全一致検証はしない。字幕・CER検証の基準は引き続きtts_text。
    """
    provider = CONFIG.get("llm", "provider", default="claude_cli")
    if provider == "openai" and not CONFIG.openai_api_key:
        provider = "claude_cli"

    difficulty = topic_store.normalize_difficulty(difficulty) or "beginner"
    topic_text = _topic_text(topic)
    meta = _topic_meta(topic)
    prompt = _build_seedance_prompt(topic, difficulty, cut_count)
    retries = int(CONFIG.get("llm", "retries", default=3))
    last_errs: list[str] = []
    for attempt in range(1, retries + 1):
        full_prompt = prompt
        if last_errs:
            full_prompt += (
                "\n\n## 前回出力の問題点（必ず修正すること）\n"
                + "\n".join(f"- {e}" for e in last_errs)
            )
        try:
            raw = _call_openai(full_prompt) if provider == "openai" else _call_claude_cli(full_prompt)
        except subprocess.TimeoutExpired:
            last_errs = [
                f"{provider} が {CONFIG.get('llm', 'timeout_sec', default=300)} 秒でタイムアウト。"
                "同じ条件で再試行すること"
            ]
            continue
        except RuntimeError as e:
            last_errs = [str(e)]
            continue
        try:
            data = normalize_generated_script(_extract_json(raw))
        except (json.JSONDecodeError, ValueError) as e:
            last_errs = [f"JSONとしてパース不能: {e}"]
            continue
        errs = validate_seedance_script(data, cut_count)
        if not errs:
            errs = recent_duplicate_errors(data)
        if not errs:
            data = _apply_line_injection(data)
            data["topic"] = topic_text
            data["difficulty"] = difficulty
            data["target_platform"] = "common"
            data["content_strategy"] = {
                key: meta[key]
                for key in ("domain", "business_function", "primary_tools", "expertise_angle", "target_persona")
                if key in meta
            }
            data["platform_angles"] = meta.get("platform_angles", {})
            return data
        last_errs = errs
    # フォールバック台本は決定論的な固定文言のため、重複チェック
    # （recent_duplicate_errors）は意図的に適用しない（上記docstring参照）。
    data = _fallback_seedance_script(topic, difficulty, last_errs)
    errs = validate_seedance_script(data, cut_count)
    if not errs:
        return data
    raise RuntimeError(
        f"Seedance台本生成が{retries}回失敗し、フォールバック台本も不合格。最終エラー: "
        + "; ".join((last_errs + errs)[:5])
    )
