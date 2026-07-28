"""SEO分析ツール - ページ分析・AI診断サービス"""

import httpx
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def fetch_page(url: str) -> dict:
    """URLからページ情報を取得・解析"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "YNTools-SEOChecker/1.0"})
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "lxml")

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"].strip()

    h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2_tags = [h.get_text(strip=True) for h in soup.find_all("h2")]
    h3_tags = [h.get_text(strip=True) for h in soup.find_all("h3")]

    img_tags = soup.find_all("img")
    images_total = len(img_tags)
    images_no_alt = sum(1 for img in img_tags if not img.get("alt"))

    links = soup.find_all("a", href=True)
    internal_links = sum(1 for a in links if a["href"].startswith("/") or url.split("/")[2] in a["href"])
    external_links = len(links) - internal_links

    body_text = soup.get_text(separator=" ", strip=True)
    word_count = len(body_text)

    canonical = ""
    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if canonical_tag and canonical_tag.get("href"):
        canonical = canonical_tag["href"]

    og_tags = {}
    for meta in soup.find_all("meta", attrs={"property": True}):
        if meta["property"].startswith("og:"):
            og_tags[meta["property"]] = meta.get("content", "")

    return {
        "url": url,
        "title": title,
        "title_length": len(title),
        "meta_description": meta_desc,
        "meta_desc_length": len(meta_desc),
        "h1_tags": h1_tags,
        "h2_tags": h2_tags[:10],
        "h3_tags": h3_tags[:10],
        "images_total": images_total,
        "images_no_alt": images_no_alt,
        "internal_links": internal_links,
        "external_links": external_links,
        "word_count": word_count,
        "canonical": canonical,
        "og_tags": og_tags,
        "has_viewport": bool(soup.find("meta", attrs={"name": "viewport"})),
        "has_charset": bool(soup.find("meta", attrs={"charset": True})),
    }


async def analyze_seo(page_data: dict) -> dict:
    """ページデータからSEOスコアとAI改善提案を生成"""
    # 基本スコア計算
    score = 100
    issues = []

    if not page_data["title"]:
        score -= 15; issues.append("titleタグが未設定")
    elif page_data["title_length"] > 60:
        score -= 5; issues.append(f"titleが長すぎます({page_data['title_length']}文字、推奨60文字以下)")
    elif page_data["title_length"] < 10:
        score -= 5; issues.append(f"titleが短すぎます({page_data['title_length']}文字)")

    if not page_data["meta_description"]:
        score -= 15; issues.append("meta descriptionが未設定")
    elif page_data["meta_desc_length"] > 160:
        score -= 5; issues.append(f"meta descriptionが長すぎます({page_data['meta_desc_length']}文字、推奨160文字以下)")

    if not page_data["h1_tags"]:
        score -= 10; issues.append("h1タグがありません")
    elif len(page_data["h1_tags"]) > 1:
        score -= 5; issues.append(f"h1タグが{len(page_data['h1_tags'])}個あります（推奨1個）")

    if page_data["images_no_alt"] > 0:
        ratio = page_data["images_no_alt"] / max(page_data["images_total"], 1)
        if ratio > 0.5:
            score -= 10; issues.append(f"画像の{page_data['images_no_alt']}/{page_data['images_total']}枚にalt属性がありません")
        else:
            score -= 5; issues.append(f"{page_data['images_no_alt']}枚の画像にalt属性がありません")

    if not page_data["has_viewport"]:
        score -= 10; issues.append("viewport metaタグがありません（モバイル対応なし）")

    if not page_data["canonical"]:
        score -= 5; issues.append("canonicalタグが未設定")

    if not page_data["og_tags"]:
        score -= 5; issues.append("OGPタグが未設定（SNSシェア時に不利）")

    if page_data["word_count"] < 300:
        score -= 10; issues.append(f"テキスト量が少ない（{page_data['word_count']}文字）")

    score = max(score, 0)

    # AI改善提案
    client = _get_client()
    page_summary = f"""
URL: {page_data['url']}
Title: {page_data['title']} ({page_data['title_length']}文字)
Meta Description: {page_data['meta_description'][:100]}... ({page_data['meta_desc_length']}文字)
H1: {', '.join(page_data['h1_tags'][:3])}
H2: {', '.join(page_data['h2_tags'][:5])}
画像: {page_data['images_total']}枚（alt未設定: {page_data['images_no_alt']}枚）
内部リンク: {page_data['internal_links']} / 外部リンク: {page_data['external_links']}
テキスト量: {page_data['word_count']}文字
検出された問題: {'; '.join(issues) if issues else 'なし'}
SEOスコア: {score}/100
"""

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "あなたはSEOの専門家です。ウェブページの分析結果から、具体的で実行可能な改善提案を5つ以内で提示してください。各提案は優先度（高/中/低）を付けて、Markdown形式で出力。"},
            {"role": "user", "content": f"以下のSEO分析結果に基づいて改善提案をしてください:\n\n{page_summary}"},
        ],
        temperature=0.3,
        max_tokens=1500,
    )
    suggestions = resp.choices[0].message.content or ""

    return {
        "score": score,
        "issues": issues,
        "suggestions": suggestions,
        "page_data": page_data,
    }
