#!/usr/bin/env python3
"""指定メールのユーザーを管理者に昇格する冪等スクリプト。

使い方:
    python scripts/promote_admin.py info@ynfactory.online
    python scripts/promote_admin.py info@ynfactory.online --demote
    python scripts/promote_admin.py --list

VPS 上での実行例（Docker内）:
    docker compose exec web python scripts/promote_admin.py info@ynfactory.online

環境変数:
    DATABASE_URL  SQLAlchemy 接続文字列（例: sqlite+aiosqlite:///./yn_tools.db）
                  未指定の場合は app.config.settings.database_url を使用する。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# yn-tools プロジェクトルートを sys.path に追加（scripts/ から実行する想定）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

# app.database の async_session（async_sessionmaker インスタンス）をそのまま利用する
from app.database import async_session
from app.users.models import User


async def promote(email: str, demote: bool = False) -> int:
    """指定メールのユーザーの is_admin フラグを更新する。

    Args:
        email: 対象ユーザーのメールアドレス。
        demote: True の場合は管理者権限を剥奪する。

    Returns:
        終了コード（0: 成功, 1: エラー）。
    """
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            print(f"[ERROR] ユーザーが見つかりません: {email}", file=sys.stderr)
            print("[HINT]  先に Google OAuth でログインしてアカウントを作成してください", file=sys.stderr)
            return 1

        if demote:
            if not user.is_admin:
                print(f"[INFO] 既に一般ユーザーです（is_admin=False）: {email}")
                return 0
            user.is_admin = False
            await db.commit()
            print(f"[OK] 管理者権限を剥奪しました: {email}  (is_admin: True -> False)")
            return 0
        else:
            if user.is_admin:
                print(f"[INFO] 既に管理者です（is_admin=True）: {email}")
                return 0
            user.is_admin = True
            await db.commit()
            print(f"[OK] 管理者に昇格しました: {email}  (is_admin: False -> True)")
            return 0


async def list_admins() -> int:
    """現在の管理者ユーザーを一覧表示する。

    Returns:
        終了コード（常に 0）。
    """
    async with async_session() as db:
        result = await db.execute(select(User).where(User.is_admin.is_(True)))
        admins = result.scalars().all()

        if not admins:
            print("[INFO] 管理者ユーザーは存在しません")
            return 0

        print(f"[INFO] 管理者ユーザー {len(admins)} 名:")
        for u in admins:
            print(f"  - id={u.id}  email={u.email}  name={u.name}  plan={u.plan}")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "email",
        nargs="?",
        help="昇格（または剥奪）するユーザーのメールアドレス",
    )
    parser.add_argument(
        "--demote",
        action="store_true",
        help="管理者権限を剥奪する（is_admin=True -> False）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="現在の管理者ユーザーを一覧表示する",
    )
    args = parser.parse_args()

    if args.list:
        sys.exit(asyncio.run(list_admins()))

    if not args.email:
        parser.error("メールアドレスを指定してください（または --list で一覧表示）")

    sys.exit(asyncio.run(promote(args.email, demote=args.demote)))


if __name__ == "__main__":
    main()
