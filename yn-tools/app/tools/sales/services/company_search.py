"""企業リスト生成サービス（user_id版）"""

import asyncio

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.tools.sales.models import SalesCompany, SalesCrmStatus


async def search_companies_google(
    query: str, region: str = "", max_results: int = 20,
) -> list[dict]:
    """Google Places API (Text Search) で企業を検索する。"""
    if not settings.google_places_api_key:
        return []

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    search_query = f"{query} {region}".strip()
    results = []
    next_page_token = None

    async with httpx.AsyncClient(timeout=30) as client:
        while len(results) < max_results:
            params = {
                "query": search_query,
                "key": settings.google_places_api_key,
                "language": "ja",
            }
            if next_page_token:
                params["pagetoken"] = next_page_token

            resp = await client.get(url, params=params)
            data = resp.json()
            if data.get("status") != "OK":
                break

            for place in data.get("results", []):
                if len(results) >= max_results:
                    break

                place_id = place.get("place_id", "")
                website_url = ""
                phone = ""

                if place_id:
                    detail = await _get_place_details(client, place_id)
                    website_url = detail.get("website", "")
                    phone = detail.get("formatted_phone_number", "")

                results.append({
                    "name": place.get("name", ""),
                    "address": place.get("formatted_address", ""),
                    "phone": phone,
                    "website_url": website_url,
                    "google_maps_url": f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                    "review_count": place.get("user_ratings_total", 0),
                    "industry": ", ".join(place.get("types", [])[:3]),
                    "region": region,
                })

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break
            await asyncio.sleep(2)

    return results


async def _get_place_details(client: httpx.AsyncClient, place_id: str) -> dict:
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "website,formatted_phone_number",
        "key": settings.google_places_api_key,
        "language": "ja",
    }
    try:
        resp = await client.get(url, params=params)
        data = resp.json()
        if data.get("status") == "OK":
            return data.get("result", {})
    except httpx.HTTPError:
        pass
    return {}


async def search_companies_scraping(
    query: str, region: str = "", max_results: int = 20,
) -> list[dict]:
    """iタウンページでフォールバック検索。"""
    results = []
    search_query = f"{query} {region}".strip()

    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": "SalesAutomationBot/1.0 (educational use)"},
        follow_redirects=True,
    ) as client:
        try:
            resp = await client.get(
                "https://itp.ne.jp/result/", params={"keyword": search_query}
            )
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "lxml")
            for listing in soup.select(".normalResultsBox")[:max_results]:
                name_tag = listing.select_one(
                    ".detailContents .name a, .detailContents .name"
                )
                phone_tag = listing.select_one(
                    ".contact .phoneNumber a, .contact .phoneNumber"
                )
                address_tag = listing.select_one(".detailContents .address")

                name = name_tag.get_text(strip=True) if name_tag else ""
                if not name:
                    continue

                results.append({
                    "name": name,
                    "address": address_tag.get_text(strip=True) if address_tag else "",
                    "phone": phone_tag.get_text(strip=True) if phone_tag else "",
                    "region": region,
                    "industry": query,
                })
                await asyncio.sleep(settings.scraping_delay_sec)
        except httpx.HTTPError:
            pass

    return results


async def search_and_save(
    db: AsyncSession, query: str, region: str = "",
    max_results: int = 20, user_id: int = 0,
) -> list[SalesCompany]:
    """企業を検索してDBに保存する。"""
    raw = await search_companies_google(query, region, max_results)
    if not raw:
        raw = await search_companies_scraping(query, region, max_results)

    saved = []
    for data in raw:
        company = SalesCompany(
            user_id=user_id,
            name=data.get("name", ""),
            address=data.get("address"),
            phone=data.get("phone"),
            website_url=data.get("website_url"),
            google_maps_url=data.get("google_maps_url"),
            review_count=data.get("review_count", 0),
            industry=data.get("industry"),
            region=data.get("region"),
        )
        db.add(company)
        await db.flush()
        db.add(SalesCrmStatus(company_id=company.id, status="未営業", score=0))
        saved.append(company)

    await db.commit()
    return saved
