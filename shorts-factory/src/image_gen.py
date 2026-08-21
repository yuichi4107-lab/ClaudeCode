"""背景画像の生成。

provider:
- card   : PILで作るデザインカード（APIキー不要・0円・デフォルト）
- openai : gpt-image-2（secrets.yaml に openai_api_key 設定時）
- gemini : NanoBanana2 / Gemini画像生成（gemini_api_key 設定時）

AIプロバイダが失敗した場合は card に自動フォールバックし、日次運用を止めない。
"""
from __future__ import annotations

import base64
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import CONFIG

W, H = 1080, 1920

# (上端色, 下端色, アクセント色) — インデックスでローテーション
PALETTES = [
    ((16, 24, 52), (44, 62, 130), (94, 234, 212)),    # 紺→藍 / ティール
    ((20, 36, 34), (16, 94, 78), (250, 204, 21)),     # 深緑→エメラルド / 黄
    ((40, 18, 60), (110, 36, 120), (251, 146, 60)),   # 紫→マゼンタ / 橙
    ((30, 26, 22), (96, 60, 30), (125, 211, 252)),    # 焦茶→琥珀 / 水色
    ((18, 30, 46), (30, 90, 140), (244, 114, 182)),   # 紺→青 / ピンク
]


def _font(size: int, black: bool = True) -> ImageFont.FreeTypeFont:
    name = "NotoSansJP-Black.otf" if black else "NotoSansJP-Bold.otf"
    return ImageFont.truetype(str(CONFIG.fonts_dir / name), size)


def _gradient(top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / H
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)
    return img


def _make_card(keyword: str, index: int, total: int, out_path: Path) -> None:
    top, bottom, accent = PALETTES[index % len(PALETTES)]
    img = _gradient(top, bottom)
    draw = ImageDraw.Draw(img, "RGBA")

    # 装飾: 大きな半透明サークルとリング
    draw.ellipse((W - 560, -260, W + 260, 560), fill=(255, 255, 255, 14))
    draw.ellipse((-300, H - 640, 420, H + 80), outline=(*accent, 60), width=22)
    draw.ellipse((W - 360, H - 420, W + 120, H + 60), fill=(*accent, 26))
    # 斜めライン
    for i in range(-4, 14):
        x0 = i * 160
        draw.line((x0, H, x0 + 700, H - 700), fill=(255, 255, 255, 8), width=3)

    # 透かしの大きな番号
    num = f"{index + 1:02d}"
    nf = _font(420)
    nb = draw.textbbox((0, 0), num, font=nf)
    draw.text(
        (W - (nb[2] - nb[0]) - 60, 360),
        num,
        font=nf,
        fill=(255, 255, 255, 26),
    )

    # 中央キーワード（収まるまで縮小）
    size = 150
    while size > 60:
        f = _font(size)
        bb = draw.textbbox((0, 0), keyword, font=f)
        if bb[2] - bb[0] <= W - 160:
            break
        size -= 8
    f = _font(size)
    bb = draw.textbbox((0, 0), keyword, font=f)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    tx, ty = (W - tw) // 2, int(H * 0.46) - th // 2
    # 軽いドロップシャドウ
    draw.text((tx + 6, ty + 8), keyword, font=f, fill=(0, 0, 0, 110))
    draw.text((tx, ty), keyword, font=f, fill=(255, 255, 255, 255))
    # アクセントバー
    bar_w = min(tw, 520)
    bx = (W - bar_w) // 2
    by = ty + th + 70
    draw.rounded_rectangle((bx, by, bx + bar_w, by + 18), radius=9, fill=(*accent, 255))

    img = img.filter(ImageFilter.GaussianBlur(0.4))
    img.save(out_path, "PNG")


def _gen_cards(keywords: list[str], out_dir: Path) -> list[Path]:
    paths = []
    total = len(keywords)
    for i, kw in enumerate(keywords):
        p = out_dir / f"bg_{i:02d}.png"
        _make_card(kw, i, total, p)
        paths.append(p)
    return paths


def _cover_resize(img: Image.Image) -> Image.Image:
    """9:16へカバーリサイズ（中央クロップ）。"""
    sw, sh = img.size
    scale = max(W / sw, H / sh)
    img = img.resize((math.ceil(sw * scale), math.ceil(sh * scale)), Image.LANCZOS)
    sw, sh = img.size
    left, top = (sw - W) // 2, (sh - H) // 2
    return img.crop((left, top, left + W, top + H))


def _ai_prompt(keyword: str, topic: str) -> str:
    return (
        "Modern flat vector illustration for a Japanese business shorts video background, "
        f"theme: practical ChatGPT/AI tips at work. Concept: {keyword} ({topic}). "
        "Clean composition with generous empty space in the center-bottom for subtitles, "
        "soft gradient background, 2-3 simple objects (laptop, robot assistant, documents), "
        "no text, no letters, no watermark, vertical 9:16."
    )


def _gen_openai(keywords: list[str], topic: str, out_dir: Path) -> list[Path]:
    from openai import OpenAI

    client = OpenAI(api_key=CONFIG.openai_api_key)
    paths = []
    for i, kw in enumerate(keywords):
        resp = client.images.generate(
            model=CONFIG.get("images", "openai_model", default="gpt-image-2"),
            prompt=_ai_prompt(kw, topic),
            size="1024x1536",
            quality=CONFIG.get("images", "openai_quality", default="medium"),
            n=1,
        )
        raw = base64.b64decode(resp.data[0].b64_json)
        p = out_dir / f"bg_{i:02d}.png"
        tmp = out_dir / f"_raw_{i:02d}.png"
        tmp.write_bytes(raw)
        with Image.open(tmp) as im:
            _cover_resize(im.convert("RGB")).save(p, "PNG")
        tmp.unlink(missing_ok=True)
        paths.append(p)
    return paths


def _gen_gemini(keywords: list[str], topic: str, out_dir: Path) -> list[Path]:
    import requests as rq

    model = CONFIG.get("images", "gemini_model", default="gemini-3.1-flash-image-preview")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={CONFIG.gemini_api_key}"
    )
    paths = []
    for i, kw in enumerate(keywords):
        body = {
            "contents": [{"parts": [{"text": _ai_prompt(kw, topic)}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": "9:16"},
            },
        }
        r = rq.post(url, json=body, timeout=120)
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        data = next(p["inlineData"]["data"] for p in parts if "inlineData" in p)
        p = out_dir / f"bg_{i:02d}.png"
        tmp = out_dir / f"_raw_{i:02d}.png"
        tmp.write_bytes(base64.b64decode(data))
        with Image.open(tmp) as im:
            _cover_resize(im.convert("RGB")).save(p, "PNG")
        tmp.unlink(missing_ok=True)
        paths.append(p)
    return paths


def generate_images(script: dict, out_dir: Path) -> tuple[list[Path], str]:
    """背景画像一式を生成。(パス一覧, 実際に使ったprovider) を返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = int(CONFIG.get("images", "count", default=4))
    keywords = [k for k in script.get("card_keywords", []) if isinstance(k, str)][:count]
    while len(keywords) < count:
        title = script.get("title", "")
        keywords.append(title if 0 < len(title) <= 9 else "AI活用術")
    topic = script.get("topic", "AI活用術")

    provider = CONFIG.get("images", "provider", default="card")
    if provider == "openai" and not CONFIG.openai_api_key:
        provider = "card"
    if provider == "gemini" and not CONFIG.gemini_api_key:
        provider = "card"

    if provider in ("openai", "gemini"):
        try:
            gen = _gen_openai if provider == "openai" else _gen_gemini
            return gen(keywords, topic, out_dir), provider
        except Exception:
            # AI画像失敗時はカードへフォールバックして日次運用を止めない
            provider = "card"
    return _gen_cards(keywords, out_dir), "card"
