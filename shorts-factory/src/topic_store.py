"""ネタ帳（topics.json）の管理。重複防止と残量管理を担う。

構造:
{
  "backlog": [{"topic": "...", "difficulty": "beginner|intermediate", "note": "..."}, ...],
  "used":    [{"topic": "...", "difficulty": "...", "date": "YYYY-MM-DD", "slug": "...", "title": "..."}, ...]
}
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from .config import CONFIG
from .fs_retry import is_transient_io_error, retry_io, run_with_timeout
from .state_io import atomic_write_json, file_lock

LOW_STOCK_THRESHOLD = 7
VALID_DIFFICULTIES = {"beginner", "intermediate"}
TOPICS_CACHE_PATH = CONFIG.runtime_dir / "cache" / "topics.json"
TOPICS_LOCK_PATH = CONFIG.state_dir / "locks" / "topics.lock"
TOPIC_SIMILARITY_THRESHOLD = 0.82
TOPIC_JACCARD_THRESHOLD = 0.74
QUEUE_RESERVED_RECENT_FILES = 120
AUTO_REPLENISH_MIN = {"beginner": 8, "intermediate": 16}
AUTO_REPLENISH_TARGET = {"beginner": 18, "intermediate": 36}
_TOPIC_NOISE_WORDS = (
    "chatgpt",
    "チャットgpt",
    "チャットジーピーティー",
    "生成ai",
    "ai",
    "方法",
    "術",
    "使い方",
    "活用",
    "させる",
    "させ",
    "して",
    "する",
    "作らせ",
    "作る",
    "作り",
    "変える",
    "できる",
    "ため",
    "まで",
    "から",
)
_TOPIC_SYNONYMS = {
    "型化": "標準化",
    "型を作る": "標準化",
    "型をつくる": "標準化",
    "テンプレ化": "標準化",
    "テンプレート化": "標準化",
    "パターン化": "標準化",
    "仕組み化": "標準化",
    "型": "標準化",
}

_BEGINNER_REPLENISH_TASKS = [
    ("会議メモを要点・TODO・期限に分ける", "meeting", "情報整理"),
    ("長いメールを失礼のない返信文に整える", "communication", "文章作成"),
    ("上司への相談文を結論から伝わる形に直す", "communication", "文章改善"),
    ("Excelの表から確認すべき数字を見つける", "analysis", "数字確認"),
    ("営業トークの言い換え案を3パターン作る", "sales", "営業改善"),
    ("マニュアルの抜け漏れをチェックリストにする", "operations", "標準化"),
    ("採用面接の質問案を職種別に作る", "hr", "採用準備"),
    ("SNS投稿文を仕事向けに言い換える", "marketing", "発信改善"),
    ("問い合わせ返信の下書きを丁寧に作る", "customer_support", "顧客対応"),
    ("研修メモから復習クイズを作る", "training", "学習定着"),
]
_BEGINNER_TOOLS = ["ChatGPT", "Claude", "Gemini", "NotebookLM"]

_INTERMEDIATE_REPLENISH_TASKS = [
    ("提案書の弱点を抽出し、反論対策まで整える", "sales", "提案品質"),
    ("営業ログから失注理由を分類し、次回提案の仮説に変える", "sales", "営業分析"),
    ("月次レポートの異常値を見つけ、確認すべき数字を絞る", "analysis", "経営管理"),
    ("業務マニュアルを現場で使えるチェックリストに変換する", "operations", "標準化"),
    ("AI導入候補を費用対効果とリスクで優先順位付けする", "ai_adoption", "導入判断"),
    ("社内FAQ候補を作り、回答品質の確認手順まで決める", "knowledge", "ナレッジ整備"),
    ("顧客の声を分類し、改善施策の優先順位へ落とし込む", "customer_success", "改善企画"),
    ("競合比較表を作り、差別化ポイントを一文で言語化する", "marketing", "競合分析"),
    ("採用要件を分解し、面接評価シートまで作る", "hr", "採用品質"),
    ("ウェビナー台本を導入・本編・CTAに分けて設計する", "marketing", "導線設計"),
    ("Google Drive資料を横断し、提案に使える根拠だけ集める", "research", "根拠整理"),
    ("Notionやスプレッドシートの業務ログから改善候補を抽出する", "operations", "業務改善"),
    ("営業資料の構成を作り、伝わりにくい箇所を直す", "presentation", "資料改善"),
    ("MakeやZapierの自動化前に、例外処理と人の確認点を洗い出す", "automation", "自動化設計"),
    ("AIの出力をそのまま使わず、事実確認の観点を3つに絞る", "quality", "品質管理"),
    ("複数AIの回答差分から、仕事で採用する案を選ぶ", "ai_tool_comparison", "AI比較"),
]
_INTERMEDIATE_TOOL_SETS = [
    ["ChatGPT", "Claude"],
    ["Gemini", "NotebookLM"],
    ["ChatGPT", "Gemini"],
    ["Claude", "Perplexity"],
    ["ChatGPT", "Canva", "Gamma"],
    ["Claude", "Make", "Zapier"],
]


def normalize_difficulty(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if value in VALID_DIFFICULTIES:
        return value
    if value in {"初級", "初心者", "beginner_jp"}:
        return "beginner"
    if value in {"中級", "中級者", "mid", "middle"}:
        return "intermediate"
    return None


def _difficulty(entry: dict) -> str:
    return normalize_difficulty(entry.get("difficulty")) or "beginner"


def _configured_count(kind: str, difficulty: str) -> int:
    defaults = AUTO_REPLENISH_MIN if kind == "min_by_difficulty" else AUTO_REPLENISH_TARGET
    configured = CONFIG.get("topics", "auto_replenish", kind, default={}) or {}
    try:
        return int(configured.get(difficulty, defaults[difficulty]))
    except (TypeError, ValueError):
        return defaults[difficulty]


def _auto_replenish_enabled() -> bool:
    return bool(CONFIG.get("topics", "auto_replenish", "enabled", default=True))


def _tool_label(tools: list[str]) -> str:
    if len(tools) == 1:
        return tools[0]
    if len(tools) == 2:
        return f"{tools[0]}と{tools[1]}"
    return "・".join(tools[:-1]) + f"・{tools[-1]}"


def _candidate_entry(
    topic: str,
    difficulty: str,
    *,
    domain: str,
    business_function: str,
    tools: list[str],
    expertise_angle: str,
) -> dict:
    return {
        "topic": topic,
        "difficulty": difficulty,
        "domain": domain,
        "business_function": business_function,
        "primary_tools": tools,
        "expertise_angle": expertise_angle,
        "target_persona": "AI導入を実務で進めたい中小企業の担当者・管理職",
        "platform_angles": {
            "x": "実務で使う判断軸を短く提示",
            "instagram": "保存して見返せる手順化",
            "tiktok": "最初のひっかかりを強くして一例で見せる",
            "youtube": "背景と注意点まで含めて検索流入を狙う",
        },
        "source": "auto_replenish_v1",
    }


def _auto_replenish_candidates(difficulty: str) -> list[dict]:
    if difficulty == "beginner":
        candidates: list[dict] = []
        for tool in _BEGINNER_TOOLS:
            for task, domain, function in _BEGINNER_REPLENISH_TASKS:
                candidates.append(
                    _candidate_entry(
                        f"{tool}で{task}方法",
                        "beginner",
                        domain=domain,
                        business_function=function,
                        tools=[tool],
                        expertise_angle="まず1つの作業にAIを使う入口を作る",
                    )
                )
        return candidates

    candidates = []
    for tools in _INTERMEDIATE_TOOL_SETS:
        label = _tool_label(tools)
        for task, domain, function in _INTERMEDIATE_REPLENISH_TASKS:
            candidates.append(
                _candidate_entry(
                    f"{label}で{task}方法",
                    "intermediate",
                    domain=domain,
                    business_function=function,
                    tools=tools,
                    expertise_angle="AI専門家として判断・設計・品質管理まで見せる",
                )
            )
    return candidates


def normalize_topic_key(topic: str | None) -> str:
    """重複判定用に、言い回しの揺れを落としたキーへ正規化する。"""
    text = unicodedata.normalize("NFKC", str(topic or "")).lower()
    for src, dest in _TOPIC_SYNONYMS.items():
        text = text.replace(src, dest)
    for word in _TOPIC_NOISE_WORDS:
        text = text.replace(word, "")
    text = re.sub(r"[\s\u3000、。・／/｜|（）()［］\[\]「」『』:：,，.!！？?ー\-]+", "", text)
    return text


def _char_grams(text: str, n: int = 2) -> set[str]:
    if len(text) <= n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _topic_similarity(a: str, b: str) -> float:
    ka = normalize_topic_key(a)
    kb = normalize_topic_key(b)
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    ratio = SequenceMatcher(None, ka, kb).ratio()
    grams_a = _char_grams(ka)
    grams_b = _char_grams(kb)
    jaccard = 0.0
    if grams_a and grams_b:
        jaccard = len(grams_a & grams_b) / len(grams_a | grams_b)
    return max(ratio, jaccard)


def is_duplicate_topic(topic: str | None, existing_topics: list[str]) -> bool:
    return duplicate_topic_match(topic, existing_topics) is not None


def duplicate_topic_match(topic: str | None, existing_topics: list[str]) -> str | None:
    key = normalize_topic_key(topic)
    if not key:
        return None
    for existing in existing_topics:
        existing_key = normalize_topic_key(existing)
        if not existing_key:
            continue
        if key == existing_key:
            return existing
        similarity = _topic_similarity(topic or "", existing)
        if similarity >= TOPIC_SIMILARITY_THRESHOLD:
            return existing
        grams_a = _char_grams(key)
        grams_b = _char_grams(existing_key)
        if grams_a and grams_b:
            jaccard = len(grams_a & grams_b) / len(grams_a | grams_b)
            if jaccard >= TOPIC_JACCARD_THRESHOLD:
                return existing
    return None


def _queue_topic_entries() -> list[dict]:
    if not CONFIG.queue_dir.exists():
        return []
    entries: list[dict] = []
    paths = sorted(CONFIG.queue_dir.glob("*.json"), reverse=True)[:QUEUE_RESERVED_RECENT_FILES]
    for path in paths:
        try:
            item = run_with_timeout(
                lambda p=path: json.loads(p.read_text(encoding="utf-8-sig")),
                timeout_sec=1.5,
                label=f"read queue topic {path.name}",
            )
        except (OSError, json.JSONDecodeError):
            continue
        topic = str(item.get("topic") or "").strip()
        title = str(item.get("title") or "").strip()
        if not topic and not title:
            continue
        entries.append(
            {
                "topic": topic,
                "title": title,
                "slug": item.get("id") or path.stem,
                "status": item.get("status"),
                "created_at": item.get("created_at"),
            }
        )
    return entries


def _reserved_topics(data: dict, *, include_queue: bool = False) -> list[str]:
    topics: list[str] = []
    for entry in data.get("used", []):
        topic = str(entry.get("topic") or "").strip()
        title = str(entry.get("title") or "").strip()
        if topic:
            topics.append(topic)
        if title:
            topics.append(title)
    if include_queue:
        for entry in _queue_topic_entries():
            topic = str(entry.get("topic") or "").strip()
            title = str(entry.get("title") or "").strip()
            if topic:
                topics.append(topic)
            if title:
                topics.append(title)
    deduped: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        key = normalize_topic_key(topic)
        if key and key not in seen:
            seen.add(key)
            deduped.append(topic)
    return deduped


def _load_once() -> dict:
    if CONFIG.topics_path.exists():
        with open(CONFIG.topics_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _write_cache(data)
        return data
    return {"backlog": [], "used": []}


def _write_cache(data: dict) -> None:
    try:
        atomic_write_json(TOPICS_CACHE_PATH, data)
    except OSError:
        pass


def _load_cache_once() -> dict:
    with open(TOPICS_CACHE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load(allow_cache: bool = True) -> dict:
    try:
        return retry_io(
            lambda: run_with_timeout(
                _load_once,
                timeout_sec=5.0,
                label="read topics.json",
            ),
            attempts=8,
            delay_sec=3.0,
        )
    except OSError as exc:
        if not allow_cache or not is_transient_io_error(exc):
            raise
        if TOPICS_CACHE_PATH.exists():
            return retry_io(_load_cache_once, attempts=3, delay_sec=1.0)
        raise


def _save_once(data: dict) -> None:
    atomic_write_json(CONFIG.topics_path, data)


def _save(data: dict) -> None:
    retry_io(
        lambda: run_with_timeout(
            lambda: _save_once(data),
            timeout_sec=8.0,
            label="write topics.json",
        ),
        attempts=8,
        delay_sec=3.0,
    )
    _write_cache(data)


def _public_topic_entry(entry: dict) -> dict:
    copied = dict(entry)
    copied["difficulty"] = _difficulty(copied)
    return copied


def next_topic_entry(
    difficulty: str | None = None,
    *,
    include_queue: bool = False,
) -> tuple[dict | None, int]:
    """指定難易度のトピックentryと残数を返す（取り出しはまだしない）。"""
    data = _load()
    backlog = data.get("backlog", [])
    if not backlog:
        return None, 0
    normalized = normalize_difficulty(difficulty)
    reserved = _reserved_topics(data, include_queue=include_queue)
    if normalized:
        for entry in backlog:
            if _difficulty(entry) == normalized and not is_duplicate_topic(entry.get("topic"), reserved):
                return _public_topic_entry(entry), backlog_count(normalized)
        return None, 0
    for entry in backlog:
        if not is_duplicate_topic(entry.get("topic"), reserved):
            return _public_topic_entry(entry), len(backlog)
    return None, 0


def next_topic(
    difficulty: str | None = None,
    *,
    include_queue: bool = False,
) -> tuple[str | None, int]:
    """指定難易度のトピック文字列と残数を返す（後方互換API）。"""
    entry, remaining = next_topic_entry(difficulty, include_queue=include_queue)
    if not entry:
        return None, remaining
    return entry.get("topic"), remaining


def consume_topic(topic: str, slug: str, title: str, difficulty: str | None = None) -> int:
    with file_lock(TOPICS_LOCK_PATH):
        return _consume_topic_locked(topic, slug, title, difficulty)


def _consume_topic_locked(topic: str, slug: str, title: str, difficulty: str | None = None) -> int:
    """トピックを used へ移動し、残数を返す。"""
    data = _load(allow_cache=False)
    used = data.setdefault("used", [])
    if any(u.get("slug") == slug for u in used):
        return len(data.get("backlog", []))
    matched = next((t for t in data.get("backlog", []) if t.get("topic") == topic), {})
    if not matched and any(u.get("topic") == topic for u in used):
        return len(data.get("backlog", []))
    topic_difficulty = normalize_difficulty(difficulty) or _difficulty(matched)
    data["backlog"] = [t for t in data.get("backlog", []) if t.get("topic") != topic]
    used_entry = {
        "topic": topic,
        "difficulty": topic_difficulty,
        "date": date.today().isoformat(),
        "slug": slug,
        "title": title,
    }
    for key in (
        "domain",
        "business_function",
        "primary_tools",
        "expertise_angle",
        "target_persona",
        "platform_angles",
        "avoid_angles",
    ):
        if key in matched:
            used_entry[key] = matched[key]
    used.append(used_entry)
    _save(data)
    return len(data["backlog"])


def recent_titles(n: int = 30) -> list[str]:
    try:
        data = _load()
    except OSError as exc:
        if is_transient_io_error(exc):
            return []
        raise
    used = data.get("used", [])
    return [u.get("title") or u.get("topic", "") for u in used[-n:]]


def add_topics(topics: list[str | dict]) -> int:
    with file_lock(TOPICS_LOCK_PATH):
        return _add_topics_locked(topics)


def _add_topics_locked(topics: list[str | dict]) -> int:
    data = _load()
    existing = [t.get("topic") for t in data.get("backlog", [])] + _reserved_topics(data)
    for item in topics:
        if isinstance(item, dict):
            topic = str(item.get("topic", "")).strip()
            difficulty = normalize_difficulty(item.get("difficulty")) or "beginner"
            entry = {**item, "topic": topic, "difficulty": difficulty}
        else:
            topic = str(item).strip()
            entry = {"topic": topic, "difficulty": "beginner"}
        if topic and not is_duplicate_topic(topic, existing):
            data.setdefault("backlog", []).append(entry)
            existing.append(topic)
    _save(data)
    return len(data["backlog"])


def _usable_backlog_count(data: dict, difficulty: str, reserved: list[str]) -> int:
    return sum(
        1
        for entry in data.get("backlog", [])
        if _difficulty(entry) == difficulty and not is_duplicate_topic(entry.get("topic"), reserved)
    )


def replenish_topics(difficulty: str | None = None, *, force: bool = False) -> dict:
    with file_lock(TOPICS_LOCK_PATH):
        return _replenish_topics_locked(difficulty, force=force)


def _replenish_topics_locked(difficulty: str | None = None, *, force: bool = False) -> dict:
    """不足したネタを内蔵候補から補充する。

    既存backlog・used・直近queueと類似する候補は追加しない。
    """
    if not force and not _auto_replenish_enabled():
        return {"enabled": False, "added": 0, "details": {}}

    normalized = normalize_difficulty(difficulty)
    targets = [normalized] if normalized else sorted(VALID_DIFFICULTIES)
    data = _load()
    reserved = _reserved_topics(data)
    existing = [
        str(entry.get("topic") or "")
        for entry in data.get("backlog", [])
        if str(entry.get("topic") or "").strip()
    ] + reserved
    details: dict[str, dict] = {}
    added_entries: list[dict] = []

    for target_difficulty in targets:
        current = _usable_backlog_count(data, target_difficulty, reserved)
        min_count = _configured_count("min_by_difficulty", target_difficulty)
        target_count = _configured_count("target_by_difficulty", target_difficulty)
        details[target_difficulty] = {
            "before": current,
            "min": min_count,
            "target": target_count,
            "added": 0,
        }
        if not force and current >= min_count:
            details[target_difficulty]["after"] = current
            continue

        for candidate in _auto_replenish_candidates(target_difficulty):
            if current >= target_count:
                break
            topic = str(candidate.get("topic") or "").strip()
            if not topic or is_duplicate_topic(topic, existing):
                continue
            data.setdefault("backlog", []).append(candidate)
            existing.append(topic)
            added_entries.append(candidate)
            current += 1
            details[target_difficulty]["added"] += 1
        details[target_difficulty]["after"] = current

    if added_entries:
        _save(data)
    return {
        "enabled": True,
        "added": len(added_entries),
        "details": details,
        "topics": [entry["topic"] for entry in added_entries],
    }


def backlog_count(difficulty: str | None = None) -> int:
    backlog = _load().get("backlog", [])
    normalized = normalize_difficulty(difficulty)
    if not normalized:
        return len(backlog)
    return sum(1 for entry in backlog if _difficulty(entry) == normalized)
