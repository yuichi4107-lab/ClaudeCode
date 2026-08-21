"""HP巡回・情報取得サービス（standalone版からそのまま移植）"""

import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

PRIORITY_PATHS = [
    "/", "/contact", "/inquiry", "/about", "/company",
    "/access", "/info", "/ask", "/form",
    "/contact.html", "/inquiry.html", "/about.html", "/company.html",
    "/otoiawase", "/toiawase",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

SNS_PATTERNS = {
    "instagram": re.compile(r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.]+"),
    "twitter": re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/[a-zA-Z0-9_]+"),
    "facebook": re.compile(r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9.]+"),
}

EXCLUDE_EMAIL_PATTERNS = [
    r".*\.(png|jpg|jpeg|gif|svg|css|js)$",
    r"^(noreply|no-reply|mailer-daemon)@",
    r"example\.(com|org|net)",
    r"wixpress\.com",
]


def _is_valid_email(email: str) -> bool:
    email_lower = email.lower()
    for pattern in EXCLUDE_EMAIL_PATTERNS:
        if re.match(pattern, email_lower):
            return False
    return True


def _classify_email(email: str) -> str:
    local = email.split("@")[0].lower()
    if local in ("info", "information"):
        return "info"
    if local in ("contact", "inquiry", "otoiawase"):
        return "contact"
    if local in ("support", "help"):
        return "support"
    return "other"


async def crawl_website(base_url: str) -> dict:
    """Webサイトを巡回して情報を抽出する。"""
    if not base_url:
        return _empty_result()

    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url

    parsed = urlparse(base_url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    emails: dict[str, str] = {}
    contact_form_urls: list[str] = []
    sns: dict[str, str | None] = {"instagram": None, "twitter": None, "facebook": None}
    description = ""
    pages_crawled = 0

    urls_to_visit = [urljoin(domain, path) for path in PRIORITY_PATHS]
    visited: set[str] = set()

    async with httpx.AsyncClient(
        timeout=15,
        headers={"User-Agent": "SalesAutomationBot/1.0 (educational use)"},
        follow_redirects=True,
    ) as client:
        # robots.txt check
        try:
            robots_resp = await client.get(urljoin(domain, "/robots.txt"))
            if robots_resp.status_code == 200:
                lines = robots_resp.text.lower().splitlines()
                for line in lines:
                    if line.strip() == "disallow: /":
                        return _empty_result()
        except httpx.HTTPError:
            pass

        for url in urls_to_visit:
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                if "text/html" not in resp.headers.get("content-type", ""):
                    continue
            except httpx.HTTPError:
                continue

            pages_crawled += 1
            html = resp.text
            soup = BeautifulSoup(html, "lxml")

            # Emails
            for email in EMAIL_REGEX.findall(html):
                if _is_valid_email(email) and email not in emails:
                    emails[email] = _classify_email(email)

            for a_tag in soup.select("a[href^='mailto:']"):
                email = a_tag["href"].replace("mailto:", "").split("?")[0].strip()
                if _is_valid_email(email) and email not in emails:
                    emails[email] = _classify_email(email)

            # Contact forms
            for form in soup.select("form"):
                action = form.get("action", "")
                form_text = form.get_text(strip=True).lower()
                if any(kw in form_text for kw in [
                    "問い合わせ", "お問合せ", "contact", "inquiry", "送信", "submit"
                ]):
                    form_url = urljoin(url, action) if action else url
                    if form_url not in contact_form_urls:
                        contact_form_urls.append(form_url)

            # SNS
            for link in soup.select("a[href]"):
                href = link.get("href", "")
                for platform, pattern in SNS_PATTERNS.items():
                    if sns[platform] is None and pattern.match(href):
                        sns[platform] = href

            # Description
            if not description:
                meta = soup.select_one('meta[name="description"]')
                if meta and meta.get("content"):
                    description = meta["content"][:300]

            # Discover contact pages
            _CONTACT_KW = [
                "contact", "inquiry", "問い合わせ", "お問合せ",
                "toiawase", "otoiawase", "form", "mail", "access", "company", "about",
            ]
            for a_tag in soup.select("a[href]"):
                href = a_tag.get("href", "")
                link_text = a_tag.get_text(strip=True).lower()
                full_url = urljoin(url, href)
                parsed_link = urlparse(full_url)

                if parsed_link.netloc != parsed.netloc:
                    continue
                if href.startswith(("#", "javascript:", "tel:", "mailto:")):
                    continue

                href_lower = href.lower()
                if full_url not in visited and full_url not in urls_to_visit:
                    if any(kw in href_lower or kw in link_text for kw in _CONTACT_KW):
                        urls_to_visit.append(full_url)

            await asyncio.sleep(settings.scraping_delay_sec)

    priority_order = {"info": 0, "contact": 1, "support": 2, "other": 3}
    sorted_emails = sorted(emails.items(), key=lambda x: priority_order.get(x[1], 99))

    return {
        "emails": [{"email": e, "type": t} for e, t in sorted_emails],
        "contact_form_urls": contact_form_urls,
        "sns": sns,
        "description": description,
        "pages_crawled": pages_crawled,
    }


def _empty_result() -> dict:
    return {
        "emails": [],
        "contact_form_urls": [],
        "sns": {"instagram": None, "twitter": None, "facebook": None},
        "description": "",
        "pages_crawled": 0,
    }
