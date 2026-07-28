"""Standalone seed script: python -m app.tools.gems.seed"""

import asyncio

from app.database import async_session, init_db
from app.tools.gems.service import seed_gems_items


async def main():
    await init_db()
    async with async_session() as db:
        count = await seed_gems_items(db)
        if count:
            print(f"Seeded {count} GEMS/GPT items.")
        else:
            print("Already seeded (skipped).")


if __name__ == "__main__":
    asyncio.run(main())
