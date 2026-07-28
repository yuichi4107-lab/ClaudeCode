"""SNS媒体別の投稿文・説明文・CTAを組み立てる。"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlencode

from .config import CONFIG

PLATFORMS = ("x", "instagram", "tiktok", "youtube")

PROFILE_MEDIUM = {
    "x": "profile",
    "instagram": "profile",
    "tiktok": "profile",
    "youtube": "channel",
}

DESCRIPTION_MEDIUM = {
    "youtube": "shorts_description",
}

PLATFORM_CTA = {
    "x": (
        "AI導入はツール選びより、最初の1業務の決め方で差が出ます。\n"
        "自社の場合を整理したい方はプロフィールの無料AI導入診断へ。"
    ),
    "instagram": (
        "保存して、AI導入前のチェックに使ってください。\n"
        "自社で何から始めるべきか知りたい方は、プロフィールの無料AI導入診断へ。"
    ),
    "tiktok": (
        "AI導入で止まっている会社は、プロフィールの無料診断で"
        "「最初の1業務」を整理できます。"
    ),
    "youtube": (
        "AIを社内にどう定着させるか迷っている方へ。\n"
        "無料AI導入診断はこちら:"
    ),
}

EXTRA_HASHTAGS = {
    "x": ["#AI導入", "#業務効率化"],
    "instagram": ["#AI導入", "#中小企業DX", "#仕事術"],
    "tiktok": ["#AI活用", "#仕事効率化", "#生成AI"],
    "youtube": ["#AI導入", "#生成AI", "#AIツール", "#業務効率化"],
}

TAG_LIMITS = {
    "x": 4,
    "instagram": 8,
    "tiktok": 5,
    "youtube": 6,
}


def _base_url() -> str:
    return str(CONFIG.get("cta", "lp_url", default="https://ai.yn-factory.com/")).rstrip("/")


def _campaign() -> str:
    return str(CONFIG.get("cta", "campaign", default="shorts_ai_consult"))


def _utm_url(platform: str, medium: str) -> str:
    params = urlencode(
        {
            "utm_source": platform,
            "utm_medium": medium,
            "utm_campaign": _campaign(),
        }
    )
    return f"{_base_url()}/?{params}"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _platform_angle(item: dict, platform: str) -> str:
    angles = item.get("platform_angles") or {}
    if isinstance(angles, dict):
        return _clean_text(angles.get(platform))
    return ""


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in ("F", "W", "A") else 1 for c in text)


def _clip_width(text: str, limit: int) -> str:
    if _width(text) <= limit:
        return text
    out = ""
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 1
        if used + w > max(0, limit - 2):
            break
        out += ch
        used += w
    return out.rstrip() + "…"


def _hashtags(item: dict, platform: str) -> list[str]:
    seen = set()
    tags = []
    for tag in list(item.get("hashtags") or []) + EXTRA_HASHTAGS.get(platform, []):
        tag = str(tag).strip()
        if not tag.startswith("#") or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= TAG_LIMITS.get(platform, 6):
            break
    return tags


def _x_text(title: str, body: str, cta: str, tags: list[str], limit: int = 270) -> str:
    tag_text = " ".join(tags)
    parts = [title, body, cta, tag_text]
    text = "\n\n".join(p for p in parts if p)
    if _width(text) <= limit:
        return text

    fixed = "\n\n".join(p for p in [title, cta, tag_text] if p)
    body_limit = max(0, limit - _width(fixed) - 4)
    body = _clip_width(body, body_limit)
    text = "\n\n".join(p for p in [title, body, cta, tag_text] if p)
    if _width(text) <= limit:
        return text

    text = "\n\n".join(p for p in [title, cta, tag_text] if p)
    if _width(text) <= limit:
        return text
    return _clip_width(text, limit)


def build_platform_copy(item: dict, platform: str) -> dict:
    """1媒体分の投稿コピーを返す。既存キューからも再計算できる純粋関数。"""
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")

    title = _clean_text(item.get("title"))
    body = _clean_text(item.get("caption"))
    angle = _platform_angle(item, platform)
    if angle and angle not in body:
        body = f"{angle}。{body}"
    cta = PLATFORM_CTA[platform]
    tags = _hashtags(item, platform)
    profile_url = _utm_url(platform, PROFILE_MEDIUM.get(platform, "profile"))
    description_url = _utm_url(platform, DESCRIPTION_MEDIUM.get(platform, "profile"))

    if platform == "x":
        text = _x_text(title, body, cta, tags)
        return {
            "title": title,
            "text": text,
            "caption": text,
            "cta": cta,
            "hashtags": tags,
            "profile_url": profile_url,
        }

    if platform == "instagram":
        caption = "\n\n".join([body, cta, " ".join(tags)])
        return {
            "title": title,
            "caption": caption,
            "cta": cta,
            "hashtags": tags,
            "profile_url": profile_url,
        }

    if platform == "tiktok":
        caption = "\n".join([title, cta, " ".join(tags)])
        return {
            "title": title,
            "caption": caption[:2000],
            "cta": cta,
            "hashtags": tags,
            "profile_url": profile_url,
        }

    description = "\n\n".join(
        [
            body,
            cta,
            description_url,
            " ".join(tags),
            f"{item.get('speaker_credit') or CONFIG.get('speaker_credit')}\n"
            "音声・映像はAIで自動生成しています",
        ]
    )
    return {
        "title": title[:95],
        "description": description,
        "caption": description,
        "cta": cta,
        "hashtags": tags,
        "profile_url": profile_url,
        "description_url": description_url,
    }


def build_platform_copy_set(item: dict) -> dict:
    return {platform: build_platform_copy(item, platform) for platform in PLATFORMS}


def copy_for_platform(item: dict, platform: str) -> dict:
    existing = (item.get("platform_copy") or {}).get(platform)
    if isinstance(existing, dict) and existing:
        return existing
    return build_platform_copy(item, platform)
