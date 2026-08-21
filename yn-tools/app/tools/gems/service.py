"""GEMS/GPT Library service - markdown parsing & DB seeding."""

import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.gems.models import GemsFavorite, GemsItem

CONTENT_DIR = Path(__file__).resolve().parent / "data"

# Folder name → (item_type, level)
FOLDER_MAP = {
    "gems": ("gem", "pro"),
    "gpts": ("gpt", "pro"),
    "gems-beginner": ("gem", "beginner"),
    "gpts-beginner": ("gpt", "beginner"),
}


def _extract_section(text: str, heading: str) -> str:
    """Extract content under a markdown heading (## or ###).
    Tolerates optional suffix in parentheses after the heading."""
    pattern = r"^#{1,3}\s+" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^#{1,3}\s|\Z)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_field(text: str, label: str) -> str:
    """Extract a **label**: value field."""
    pattern = rf"\*\*{re.escape(label)}\*\*:\s*(.+)"
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def _extract_code_block(text: str) -> str:
    """Extract content from first ``` code block."""
    m = re.search(r"```\n?(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_markdown(filepath: Path, item_type: str, level: str) -> dict:
    """Parse a GEMS/GPT markdown file into a dict for DB insertion."""
    text = filepath.read_text(encoding="utf-8")
    slug = f"{item_type}-{level}-{filepath.stem}"

    # Title from first heading
    title_match = re.match(r"^#\s+(.+?)(?:\s*—\s*.+)?$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else filepath.stem

    # Basic info
    category = _extract_field(text, "カテゴリ")
    target_user = _extract_field(text, "対象ユーザー")
    use_case = _extract_field(text, "想定利用シーン")

    # Gem/GPT settings
    name_section = _extract_section(text, "Gem名") or _extract_section(text, "GPT名")
    name = name_section.split("\n")[0].strip() if name_section else title

    description = _extract_section(text, "説明文")

    # Extract prompt: find the code block after "### インストラクション"
    # Can't use _extract_section because code blocks may contain ## headings
    prompt_match = re.search(
        r"^#{1,3}\s+インストラクション[^\n]*\n.*?```\n?(.*?)```",
        text, re.MULTILINE | re.DOTALL,
    )
    prompt_content = prompt_match.group(1).strip() if prompt_match else ""

    starters = _extract_section(text, "会話スターター")
    feature_settings = _extract_section(text, "機能設定")

    # Usage guide - combine sub-sections
    guide_parts = []
    for heading in ["こんなときに使えます", "使い方のコツ", "入力例と出力例",
                    "入力例（具体的なビジネスシーンの例）"]:
        part = _extract_section(text, heading)
        if part:
            guide_parts.append(f"### {heading}\n{part}")
    usage_guide = "\n\n".join(guide_parts)

    return {
        "slug": slug,
        "title": title,
        "item_type": item_type,
        "level": level,
        "category": category,
        "target_user": target_user,
        "use_case": use_case,
        "name": name,
        "description": description,
        "prompt_content": prompt_content,
        "conversation_starters": starters,
        "feature_settings": feature_settings,
        "usage_guide": usage_guide,
    }


async def seed_gems_items(db: AsyncSession) -> int:
    """Parse all markdown files and seed into DB. Returns count of items added."""
    existing = await db.execute(select(func.count(GemsItem.id)))
    if existing.scalar() > 0:
        return 0  # Already seeded

    count = 0
    for folder_name, (item_type, level) in FOLDER_MAP.items():
        folder = CONTENT_DIR / folder_name
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            data = parse_markdown(md_file, item_type, level)
            db.add(GemsItem(**data))
            count += 1

    await db.commit()
    return count


async def get_categories(db: AsyncSession) -> list[str]:
    """Get distinct categories."""
    result = await db.execute(
        select(GemsItem.category).where(GemsItem.level != "beginner")
        .distinct().order_by(GemsItem.category)
    )
    return [r for r in result.scalars().all() if r]


async def search_items(
    db: AsyncSession,
    item_type: str | None = None,
    category: str | None = None,
    q: str | None = None,
) -> list[GemsItem]:
    """Search/filter GEMS/GPT items."""
    stmt = select(GemsItem).where(GemsItem.level != "beginner")
    if item_type:
        stmt = stmt.where(GemsItem.item_type == item_type)
    if category:
        stmt = stmt.where(GemsItem.category == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            GemsItem.title.ilike(like)
            | GemsItem.name.ilike(like)
            | GemsItem.description.ilike(like)
        )
    stmt = stmt.order_by(GemsItem.item_type, GemsItem.slug)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_user_favorite_ids(db: AsyncSession, user_id: int) -> set[int]:
    """Get set of item IDs favorited by user."""
    result = await db.execute(
        select(GemsFavorite.item_id).where(GemsFavorite.user_id == user_id)
    )
    return set(result.scalars().all())
