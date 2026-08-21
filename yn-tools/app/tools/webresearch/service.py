"""AI Webリサーチャー - Webページ取得・AI分析"""

import re
from urllib.parse import urlparse

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


# ---------- Webページ取得 ----------

MAX_CONTENT_CHARS = 80_000


async def fetch_page(url: str) -> dict:
    """URLからページを取得してテキスト抽出"""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    async with httpx.AsyncClient(
        timeout=20,
        headers={"User-Agent": "YNTools-WebResearcher/1.0"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    if "text/html" not in content_type:
        raise ValueError(f"HTMLではないコンテンツです: {content_type}")

    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    # タイトル
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # メタ情報
    meta_desc = ""
    meta_tag = soup.select_one('meta[name="description"]')
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"]

    # 不要要素除去
    for tag in soup.select("script, style, nav, footer, header, aside, iframe, noscript"):
        tag.decompose()

    # テキスト抽出
    text = soup.get_text(separator="\n", strip=True)
    # 連続改行を2つまでに
    text = re.sub(r"\n{3,}", "\n\n", text)

    if len(text) > MAX_CONTENT_CHARS:
        text = text[:MAX_CONTENT_CHARS] + "\n\n...(以降省略)"

    # リンク抽出
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        link_text = a.get_text(strip=True)
        if href.startswith(("http://", "https://")) and link_text:
            links.append({"text": link_text[:100], "url": href})
            if len(links) >= 30:
                break

    return {
        "url": str(resp.url),
        "title": title,
        "meta_description": meta_desc,
        "text": text,
        "links": links,
        "status_code": resp.status_code,
    }


async def fetch_multiple_pages(urls: list[str]) -> list[dict]:
    """複数URLを取得"""
    results = []
    for url in urls[:5]:  # 最大5ページ
        try:
            page = await fetch_page(url)
            results.append(page)
        except Exception as e:
            results.append({"url": url, "error": str(e)})
    return results


# ---------- AI分析 ----------

async def analyze_page(text: str, title: str, url: str, analysis_type: str = "summary") -> str:
    """ページ内容をAIで分析"""
    instructions = {
        "summary": (
            "このWebページの内容を分かりやすく要約してください。\n"
            "- 主要なポイントを箇条書きで整理\n"
            "- 重要な数値データがあれば抽出\n"
            "- ページの目的・対象読者を簡潔に説明"
        ),
        "competitor": (
            "このWebページを競合分析の観点で分析してください。\n"
            "- 提供サービス/製品の概要\n"
            "- 価格帯（記載があれば）\n"
            "- 強み・差別化ポイント\n"
            "- ターゲット顧客\n"
            "- マーケティング手法の特徴"
        ),
        "seo": (
            "このWebページをSEO観点で分析してください。\n"
            "- タイトルタグの評価\n"
            "- 推定ターゲットキーワード\n"
            "- コンテンツの構造（見出し構成）\n"
            "- 改善提案（3〜5点）"
        ),
        "extract_data": (
            "このWebページから構造化データを抽出してください。\n"
            "- 企業情報（社名、所在地、連絡先等）\n"
            "- 製品/サービス一覧\n"
            "- 価格情報\n"
            "- 日付・イベント情報\n"
            "Markdown表形式で整理してください。"
        ),
    }

    instruction = instructions.get(analysis_type, instructions["summary"])

    return await _call_llm(
        system="あなたはWebリサーチの専門家です。提供されたWebページの内容を分析してください。",
        user=f"【URL】{url}\n【タイトル】{title}\n\n【分析指示】\n{instruction}\n\n【ページ内容】\n{text}",
    )


async def compare_pages(pages: list[dict]) -> str:
    """複数ページの比較分析"""
    pages_text = ""
    for i, page in enumerate(pages, 1):
        if "error" in page:
            pages_text += f"\n--- サイト{i}: {page['url']} ---\n取得エラー: {page['error']}\n"
        else:
            # 各ページは5000文字に制限
            text = page["text"][:5000]
            pages_text += f"\n--- サイト{i}: {page['url']} ---\n【タイトル】{page['title']}\n{text}\n"

    return await _call_llm(
        system="あなたは市場調査・競合分析の専門家です。複数のWebサイトを比較分析してください。",
        user=(
            "以下の複数サイトを比較分析してください。\n"
            "- 各サイトの概要\n"
            "- 共通点と相違点\n"
            "- 強み・弱みの比較表（Markdown）\n"
            "- 総合的な所見\n\n"
            f"{pages_text}"
        ),
    )


async def _call_llm(system: str, user: str) -> str:
    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
