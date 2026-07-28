# yntools セミナーデモ版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** yntools を `demo.ynfactory.online` で「Claude Code で作れる例」として無料公開できるよう、`DEMO_MODE` 環境変数で挙動を切り替えるハイブリッド構成を実装する。本番（`tools.ynfactory.online`）は影響ゼロ。

**Architecture:** 同一リポジトリ・同一 Dockerfile を使い、`docker-compose.demo.yml` で `DEMO_MODE=true` を渡す。アプリ側は `settings.demo_mode` をチェックして、認証バイパス（自動ゲストユーザー）・Stripe バイパス・料金 UI 非表示・「Claude Code 開発」バッジ表示・トップページ差し替え・DB をインメモリ化、を行う。

**Tech Stack:** FastAPI / SQLAlchemy(async) / Jinja2 / Postgres(本番) → SQLite in-memory(デモ) / Stripe / Docker / Nginx。

**Spec:** `docs/superpowers/specs/2026-05-04-yntools-seminar-demo-design.md`

---

## File Structure

| 種別 | パス | 役割 |
|---|---|---|
| Modify | `yn-tools/app/config.py` | `demo_mode: bool` 設定追加 |
| Create | `yn-tools/app/core/__init__.py` | パッケージ初期化（空） |
| Create | `yn-tools/app/core/demo.py` | デモモード判定ヘルパ・ゲストユーザー定数 |
| Modify | `yn-tools/app/auth/dependencies.py` | DEMO_MODE 時にゲストユーザーを返す |
| Modify | `yn-tools/app/billing/router.py` | DEMO_MODE 時に全エンドポイント 404 |
| Modify | `yn-tools/app/main.py` | ランディングを DEMO_MODE で分岐、テンプレートに `demo_mode` を渡すグローバル化 |
| Create | `yn-tools/app/templates/landing_demo.html` | デモ専用トップページ |
| Modify | `yn-tools/app/templates/base.html` | ヘッダー文言・「Claude Code 開発」バッジ・料金リンク非表示 |
| Modify | `yn-tools/app/templates/dashboard.html` | 料金表記とアップグレード CTA を `not demo_mode` で囲う |
| Modify | `yn-tools/app/database.py` | DEMO_MODE 時に DB URL を `sqlite+aiosqlite:///:memory:` に強制差し替え |
| Create | `yn-tools/docker-compose.demo.yml` | デモ用 compose（コンテナ名・ポート分離、ボリューム未マウント） |
| Create | `yn-tools/.env.demo.example` | デモ用 env テンプレート |
| Create | `yn-tools/tests/test_demo_mode.py` | DEMO_MODE のユニットテスト |
| Create | `yn-tools/scripts/deploy-demo.sh` | VPS 上での再ビルド＆起動コマンド |
| Create | `docs/operations/demo-nginx.conf.example` | Nginx 設定の参考 |

---

## Task 1: `demo_mode` 設定とヘルパの追加（TDD）

**Files:**
- Modify: `yn-tools/app/config.py`
- Create: `yn-tools/app/core/__init__.py`
- Create: `yn-tools/app/core/demo.py`
- Create: `yn-tools/tests/test_demo_mode.py`

- [ ] **Step 1: テストを書く（失敗する状態）**

`yn-tools/tests/test_demo_mode.py` を新規作成:

```python
"""Tests for DEMO_MODE helper and settings."""

import importlib

import pytest


def test_settings_default_demo_mode_false(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    from app import config
    importlib.reload(config)
    assert config.settings.demo_mode is False


def test_settings_demo_mode_true_from_env(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    assert config.settings.demo_mode is True


def test_guest_user_has_full_access(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.core.demo import GUEST_USER
    assert GUEST_USER.has_full_access is True
    assert GUEST_USER.is_admin is False
    assert GUEST_USER.email == "guest@demo.ynfactory.online"
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: FAIL（`demo_mode` 未定義 / `app.core.demo` 未存在）

- [ ] **Step 3: `app/config.py` に `demo_mode` フィールドを追加**

`Settings` クラス内、`trial_days` の下あたりに追加:

```python
    # Seminar demo mode
    demo_mode: bool = False
```

- [ ] **Step 4: `app/core/__init__.py` を空ファイルで作成**

```python
```

- [ ] **Step 5: `app/core/demo.py` を作成（GUEST_USER 定数）**

```python
"""Demo mode helpers (used when DEMO_MODE=true)."""

from datetime import datetime, timedelta
from types import SimpleNamespace


def _build_guest_user() -> SimpleNamespace:
    """Return an in-memory guest user shaped like app.users.models.User.

    Not persisted to DB — used only for templates and route dependencies
    when DEMO_MODE=true.
    """
    far_future = datetime.utcnow() + timedelta(days=365 * 10)
    return SimpleNamespace(
        id=0,
        google_id="demo-guest",
        email="guest@demo.ynfactory.online",
        name="ゲスト（デモ）",
        avatar_url=None,
        plan="all_tools",
        trial_ends_at=far_future,
        stripe_customer_id=None,
        stripe_subscription_id=None,
        is_active=True,
        is_admin=False,
        # Properties on the real model
        has_active_plan=True,
        has_full_access=True,
        is_in_trial=False,
        has_paid_plan_during_trial=False,
    )


GUEST_USER = _build_guest_user()
```

- [ ] **Step 6: テスト再実行（成功確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: PASS（3 tests）

- [ ] **Step 7: コミット**

```bash
git add yn-tools/app/config.py yn-tools/app/core/__init__.py yn-tools/app/core/demo.py yn-tools/tests/test_demo_mode.py
git commit -m "feat(demo): add DEMO_MODE setting and GUEST_USER helper"
```

---

## Task 2: 認証バイパス（ゲスト自動ログイン）

**Files:**
- Modify: `yn-tools/app/auth/dependencies.py`
- Modify: `yn-tools/tests/test_demo_mode.py`

- [ ] **Step 1: テストを追加**

`yn-tools/tests/test_demo_mode.py` の末尾に追記:

```python
import asyncio


def test_get_current_user_returns_guest_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.auth import dependencies
    importlib.reload(dependencies)

    class _FakeRequest:
        session: dict = {}

    user = asyncio.run(dependencies.get_current_user(_FakeRequest(), db=None))
    assert user is not None
    assert user.email == "guest@demo.ynfactory.online"


def test_require_login_returns_guest_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.auth import dependencies
    importlib.reload(dependencies)

    user = asyncio.run(dependencies.require_login(user=None))
    assert user is not None
    assert user.email == "guest@demo.ynfactory.online"
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: 既存 3 PASS、新規 2 FAIL

- [ ] **Step 3: `app/auth/dependencies.py` を修正**

ファイル冒頭の import 群の下に共通ガードを追加し、各依存関数の先頭でデモモードを判定:

```python
"""Auth dependencies for FastAPI route injection."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.demo import GUEST_USER
from app.database import get_db
from app.users.models import User, UserToolSubscription


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Get current logged-in user from session cookie. Returns None if not logged in."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and not user.is_active:
        return None
    return user


async def require_login(
    user: User | None = Depends(get_current_user),
) -> User:
    """Require authenticated user. Raises 401 if not logged in."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    if not user:
        raise HTTPException(status_code=401, detail="login_required")
    return user


async def require_active_plan(
    user: User = Depends(require_login),
) -> User:
    """Require user with active plan (pro or within trial). Raises 402 if expired."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    if user.has_active_plan:
        return user
    raise HTTPException(status_code=402, detail="plan_expired")


def require_tool_access(tool_slug: str):
    """Factory that returns a dependency checking access to a specific tool."""

    async def _check(
        request: Request,
        user: User = Depends(require_login),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if settings.demo_mode:
            return GUEST_USER  # type: ignore[return-value]
        if user.has_full_access:
            return user
        if user.plan == "per_tool":
            result = await db.execute(
                select(UserToolSubscription).where(
                    UserToolSubscription.user_id == user.id,
                    UserToolSubscription.tool_slug == tool_slug,
                    UserToolSubscription.is_active == True,
                )
            )
            if result.scalar_one_or_none():
                return user
        raise HTTPException(status_code=402, detail="tool_not_subscribed")

    return _check


async def require_admin(
    user: User = Depends(require_login),
) -> User:
    """Require admin user. Raises 403 if not admin."""
    if settings.demo_mode:
        # 管理者機能はデモでは閉じる
        raise HTTPException(status_code=404, detail="not_found")
    if user.is_admin:
        return user
    raise HTTPException(status_code=403, detail="admin_required")
```

- [ ] **Step 4: テスト再実行（成功確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: 5 PASS

- [ ] **Step 5: コミット**

```bash
git add yn-tools/app/auth/dependencies.py yn-tools/tests/test_demo_mode.py
git commit -m "feat(demo): bypass auth and inject GUEST_USER when DEMO_MODE=true"
```

---

## Task 3: Stripe / Billing バイパス

**Files:**
- Modify: `yn-tools/app/billing/router.py`
- Modify: `yn-tools/tests/test_demo_mode.py`

- [ ] **Step 1: 既存ルーターを確認してテストを書く**

```bash
head -30 "yn-tools/app/billing/router.py"
```

`tests/test_demo_mode.py` の末尾に追記:

```python
def test_billing_router_returns_404_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    from app import config
    importlib.reload(config)
    from app.billing import router as billing_router_mod
    importlib.reload(billing_router_mod)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(billing_router_mod.router)
    client = TestClient(app)
    # 既知の billing エンドポイントを叩く（実装に応じて 1 つ選ぶ）
    res = client.post("/billing/webhook")
    assert res.status_code == 404
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py::test_billing_router_returns_404_in_demo_mode -v
```
Expected: FAIL（404 以外が返る）

- [ ] **Step 3: `app/billing/router.py` 冒頭にガードを追加**

ファイルの最初の `router = APIRouter(...)` 行の直後に、router 全体に効くミドルウェア依存を追加。具体的には全ルートに対して `dependencies=[Depends(_block_in_demo)]` を付ける形で実装する。

```python
from fastapi import APIRouter, Depends, HTTPException

from app.config import settings


def _block_in_demo() -> None:
    if settings.demo_mode:
        raise HTTPException(status_code=404, detail="not_found")


router = APIRouter(prefix="/billing", tags=["billing"], dependencies=[Depends(_block_in_demo)])
```

既存の `router = APIRouter(prefix="/billing", tags=["billing"])` をこの形に置換する。`Depends` / `HTTPException` の import が無ければ追加。

- [ ] **Step 4: テスト再実行（成功確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: 6 PASS

- [ ] **Step 5: コミット**

```bash
git add yn-tools/app/billing/router.py yn-tools/tests/test_demo_mode.py
git commit -m "feat(demo): return 404 from /billing/* when DEMO_MODE=true"
```

---

## Task 4: テンプレートに `demo_mode` をグローバル提供

**Files:**
- Modify: `yn-tools/app/main.py`

- [ ] **Step 1: Jinja2 グローバル変数として `demo_mode` を提供**

`app/main.py` の `templates = Jinja2Templates(directory="app/templates")` 行の直後に追加:

```python
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["demo_mode"] = settings.demo_mode
```

- [ ] **Step 2: 同様に他で `Jinja2Templates` を作っているルーターにも globals を仕込む（DRY化）**

`yn-tools/app/` 配下で `Jinja2Templates(` を使う箇所を確認:

```bash
grep -rn "Jinja2Templates(" yn-tools/app
```

各箇所で同じ行を追加するのは手間なので、共通ヘルパを作る。

`yn-tools/app/core/templates.py` を新規作成:

```python
"""Shared Jinja2Templates factory that injects DEMO_MODE globally."""

from fastapi.templating import Jinja2Templates

from app.config import settings


def make_templates(directory: str = "app/templates") -> Jinja2Templates:
    t = Jinja2Templates(directory=directory)
    t.env.globals["demo_mode"] = settings.demo_mode
    return t
```

`app/main.py` を修正:

```python
from app.core.templates import make_templates
# 既存の `templates = Jinja2Templates(...)` を置換
templates = make_templates("app/templates")
```

各ツールルーターを順次 `make_templates` 経由に切り替えるかは時間との相談。まず `main.py` のみ対応（base.html がここから渡される変数を共有するわけではないので、Jinja2 グローバルとして仕込むのが正解。よって `make_templates` を使う各場所で globals が反映される）。

- [ ] **Step 3: 動作確認（手動）**

```bash
cd yn-tools && DEMO_MODE=true uvicorn app.main:app --reload --port 8001
```
ブラウザで `http://localhost:8001/` を開き、エラーなく動くこと（UI はまだ変更していないので見た目は本番のまま）。

- [ ] **Step 4: コミット**

```bash
git add yn-tools/app/main.py yn-tools/app/core/templates.py
git commit -m "feat(demo): expose demo_mode flag to Jinja2 templates globally"
```

---

## Task 5: トップページ差し替え（landing_demo.html）

**Files:**
- Create: `yn-tools/app/templates/landing_demo.html`
- Modify: `yn-tools/app/main.py`

- [ ] **Step 1: `landing_demo.html` を作成**

`yn-tools/app/templates/landing_demo.html`:

```html
{% extends "base.html" %}
{% block title %}Claude Code 開発デモ｜YN Factory{% endblock %}

{% block content %}
<section class="hero" style="padding:4rem 1.5rem;text-align:center;">
  <h1 style="font-size:2.4rem;margin-bottom:1rem;">
    🤖 これは全て <span style="color:#a37bff;">Claude Code</span> で作りました
  </h1>
  <p style="font-size:1.1rem;color:#666;max-width:760px;margin:0 auto 2rem;">
    本デモは YN Factory のセミナー教材です。<br>
    37 種類の業務 SaaS ツールを、Claude Code を使って実装した実例をそのままご覧いただけます。
    ログイン不要・無料で全機能を試せます（保存データはセッション中のみ保持されます）。
  </p>
  <a href="/dashboard" class="btn btn-primary" style="padding:0.9rem 2rem;font-size:1.1rem;">
    ツール一覧を見る →
  </a>
</section>

<section style="padding:2rem 1.5rem;max-width:960px;margin:0 auto;">
  <h2 style="font-size:1.4rem;margin-bottom:1rem;">このデモについて</h2>
  <ul style="line-height:1.9;">
    <li>本番版（販売中）は <a href="https://tools.ynfactory.online" target="_blank" rel="noopener">tools.ynfactory.online</a></li>
    <li>このデモはセミナー説明用で、課金・ログインは無効化されています</li>
    <li>生成・保存データはコンテナ再起動で消えます</li>
  </ul>
</section>
{% endblock %}
```

- [ ] **Step 2: `app/main.py` の `landing` ルートを DEMO_MODE で分岐**

既存 `landing` 関数を以下に置換:

```python
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request, user=Depends(get_current_user)):
    """Landing page (top) or redirect to dashboard if logged in."""
    if settings.demo_mode:
        # デモモード: ゲストユーザーで即ダッシュボードへ
        from fastapi.responses import RedirectResponse
        # ただしトップを叩いた一度はデモ説明ページを見せる（?skip=1 でダッシュボードへ）
        if request.query_params.get("skip") == "1":
            return RedirectResponse(url="/dashboard", status_code=303)
        return templates.TemplateResponse(
            request, "landing_demo.html", {"user": user}
        )
    if user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request, "landing.html", {"user": None}
    )
```

- [ ] **Step 3: 動作確認（手動）**

```bash
cd yn-tools && DEMO_MODE=true uvicorn app.main:app --reload --port 8001
```
- `http://localhost:8001/` → デモ説明ページが表示される
- `/dashboard` → ゲストとしてログイン済み状態で表示される

- [ ] **Step 4: コミット**

```bash
git add yn-tools/app/templates/landing_demo.html yn-tools/app/main.py
git commit -m "feat(demo): replace landing page with seminar intro when DEMO_MODE=true"
```

---

## Task 6: base / dashboard テンプレートの料金 UI 非表示＋バッジ追加

**Files:**
- Modify: `yn-tools/app/templates/base.html`
- Modify: `yn-tools/app/templates/dashboard.html`

- [ ] **Step 1: 現状の base.html を確認**

```bash
grep -n -E "料金|プラン|アップグレード|サブスク|¥|円/月|請求" yn-tools/app/templates/base.html yn-tools/app/templates/dashboard.html
```

- [ ] **Step 2: `base.html` のヘッダー文言と料金リンクを `demo_mode` で切替**

`base.html` 内のサイトタイトル／ヘッダー文言を以下のパターンで囲う。実際の行は grep で特定したものに置換:

```jinja
{% if demo_mode %}
  <span class="brand">Claude Code 開発デモ｜YN Factory</span>
{% else %}
  <span class="brand">YN Factory ツール集</span>
{% endif %}
```

ヘッダー／サイドバーにある「料金プラン」「請求情報」「アップグレード」リンクを以下で囲う:

```jinja
{% if not demo_mode %}
  <a href="/billing/...">料金プラン</a>
  <!-- 既存の請求／プランリンク群 -->
{% endif %}
```

footer 直前に「Claude Code 開発」バッジを追加:

```jinja
{% if demo_mode %}
<div class="demo-badge" style="position:fixed;bottom:1rem;right:1rem;background:#1f1f1f;color:#fff;padding:0.6rem 1rem;border-radius:8px;font-size:0.85rem;box-shadow:0 4px 12px rgba(0,0,0,0.2);z-index:9999;">
  🤖 このサイトは全て <strong>Claude Code</strong> で開発されました
</div>
{% endif %}
```

- [ ] **Step 3: `dashboard.html` の料金表記を非表示化**

`dashboard.html` 内、`¥`／`円/月`／「アップグレード」「プラン変更」「トライアル残り」等の表記を含むブロックを `{% if not demo_mode %}` ... `{% endif %}` で囲う。具体的な行番号は Step 1 の grep で取得した結果に従って個別対応。

代わりにダッシュボード上部に小さな案内を表示:

```jinja
{% if demo_mode %}
<div class="demo-notice" style="background:#fff8d6;border:1px solid #ffd84d;padding:0.8rem 1rem;border-radius:6px;margin-bottom:1rem;">
  これはセミナー用デモです。全ツールが無料で試せます（データはセッション中のみ保持）。
</div>
{% endif %}
```

- [ ] **Step 4: 動作確認（手動）**

```bash
cd yn-tools && DEMO_MODE=true uvicorn app.main:app --reload --port 8001
```
- ダッシュボードに料金表記が一切出ない
- 右下に「Claude Code で開発」バッジが固定表示
- ヘッダーが「Claude Code 開発デモ｜YN Factory」になっている

本番動作チェック:

```bash
cd yn-tools && DEMO_MODE=false uvicorn app.main:app --reload --port 8002
```
- `http://localhost:8002/` で従来どおり料金表記が表示される
- バッジは出ない

- [ ] **Step 5: コミット**

```bash
git add yn-tools/app/templates/base.html yn-tools/app/templates/dashboard.html
git commit -m "feat(demo): hide pricing UI and show Claude Code dev badge when demo_mode"
```

---

## Task 7: DB をインメモリ化／本番ボリューム遮断

**Files:**
- Modify: `yn-tools/app/database.py`
- Modify: `yn-tools/tests/test_demo_mode.py`

- [ ] **Step 1: テストを追加**

`tests/test_demo_mode.py` 末尾:

```python
def test_database_url_forced_to_inmemory_in_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pw@host/db")
    from app import config
    importlib.reload(config)
    from app import database
    importlib.reload(database)
    assert "sqlite" in database.effective_database_url()
    assert ":memory:" in database.effective_database_url()
```

- [ ] **Step 2: テスト実行（失敗確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py::test_database_url_forced_to_inmemory_in_demo_mode -v
```
Expected: FAIL（`effective_database_url` 未定義）

- [ ] **Step 3: `app/database.py` を修正**

ファイル先頭で `settings.database_url` を直接使っている箇所を、新しいヘルパ `effective_database_url()` 経由に変更:

```python
from app.config import settings


def effective_database_url() -> str:
    """Return the DB URL to actually use, forcing in-memory SQLite under DEMO_MODE."""
    if settings.demo_mode:
        return "sqlite+aiosqlite:///:memory:"
    return settings.database_url


# 既存の create_async_engine(settings.database_url, ...) を以下に置換
engine = create_async_engine(effective_database_url(), ...)
```

`async_session` / `init_db` / `Base` 周りはそのまま。

- [ ] **Step 4: テスト再実行（成功確認）**

```bash
cd yn-tools && pytest tests/test_demo_mode.py -v
```
Expected: 7 PASS

- [ ] **Step 5: 起動確認**

```bash
cd yn-tools && DEMO_MODE=true uvicorn app.main:app --port 8001
```
ログに Postgres への接続試行が出ず、SQLite in-memory で起動すること。

- [ ] **Step 6: コミット**

```bash
git add yn-tools/app/database.py yn-tools/tests/test_demo_mode.py
git commit -m "feat(demo): force in-memory SQLite when DEMO_MODE=true to isolate from prod DB"
```

---

## Task 8: docker-compose.demo.yml と .env.demo.example

**Files:**
- Create: `yn-tools/docker-compose.demo.yml`
- Create: `yn-tools/.env.demo.example`

- [ ] **Step 1: `docker-compose.demo.yml` を作成**

```yaml
# Seminar demo deployment.
# - Reuses the same Dockerfile / source as production (docker-compose.yml).
# - DEMO_MODE=true: app forces in-memory SQLite, bypasses Stripe/auth, hides pricing UI.
# - No volumes mounted: container restart wipes data.
# - Different container name + host port to coexist with production on the same VPS.

services:
  app:
    build: .
    container_name: yn-tools-demo
    restart: unless-stopped
    ports:
      - "8081:8000"
    env_file:
      - .env.demo
    environment:
      - DEMO_MODE=true
      - APP_ENV=demo
      # DATABASE_URL is overridden to in-memory by app code, but set a stub for safety.
      - DATABASE_URL=sqlite+aiosqlite:///:memory:
      # Stripe / Google OAuth keys intentionally absent.
```

- [ ] **Step 2: `.env.demo.example` を作成**

```dotenv
# Demo deployment env. Copy to .env.demo on the VPS.
# Stripe / Google OAuth keys are intentionally NOT set — DEMO_MODE bypasses them.

SECRET_KEY=replace-with-random-string-for-demo-sessions
DEMO_MODE=true
APP_ENV=demo

# Optional: if any tool genuinely needs an external API key for the demo
# (e.g. OPENAI_API_KEY for AI features), set it here.
# OPENAI_API_KEY=
```

- [ ] **Step 3: ローカル起動確認**

```bash
cd yn-tools && cp .env.demo.example .env.demo
# .env.demo の SECRET_KEY を適当な値に書き換える
docker compose -f docker-compose.demo.yml up -d --build
curl -I http://localhost:8081/
docker compose -f docker-compose.demo.yml logs --tail=50 app
docker compose -f docker-compose.demo.yml down
```
Expected: `200 OK` または `303` リダイレクト、ログに `DEMO_MODE` 起因のエラーなし

- [ ] **Step 4: コミット**

```bash
git add yn-tools/docker-compose.demo.yml yn-tools/.env.demo.example
git commit -m "chore(demo): add docker-compose.demo.yml and .env.demo.example"
```

---

## Task 9: Nginx 設定例とデプロイスクリプト

**Files:**
- Create: `docs/operations/demo-nginx.conf.example`
- Create: `yn-tools/scripts/deploy-demo.sh`

- [ ] **Step 1: Nginx 設定例を作成**

`docs/operations/demo-nginx.conf.example`:

```nginx
# /etc/nginx/sites-available/demo.ynfactory.online
# After placing this file:
#   sudo ln -s /etc/nginx/sites-available/demo.ynfactory.online /etc/nginx/sites-enabled/
#   sudo certbot --nginx -d demo.ynfactory.online
#   sudo nginx -t && sudo systemctl reload nginx

server {
    listen 80;
    server_name demo.ynfactory.online;

    location / {
        proxy_pass         http://127.0.0.1:8081;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        client_max_body_size 50M;
    }
}
```

- [ ] **Step 2: VPS 用デプロイスクリプトを作成**

`yn-tools/scripts/deploy-demo.sh`:

```bash
#!/usr/bin/env bash
# Demo redeploy on ConoHa VPS.
# Run from /opt/yn-tools (or wherever the demo checkout lives).
set -euo pipefail

cd "$(dirname "$0")/.."

git pull --ff-only

# Always rebuild — restart alone won't pick up code changes baked via Dockerfile COPY.
docker compose -f docker-compose.demo.yml up -d --build --force-recreate

docker compose -f docker-compose.demo.yml ps
docker compose -f docker-compose.demo.yml logs --tail=80 app
```

実行権限:

```bash
chmod +x yn-tools/scripts/deploy-demo.sh
```

- [ ] **Step 3: コミット**

```bash
git add docs/operations/demo-nginx.conf.example yn-tools/scripts/deploy-demo.sh
git commit -m "docs(demo): add Nginx config example and deploy-demo.sh"
```

---

## Task 10: VPS 上での実デプロイ（手動）

このタスクはコードを変更しません。VPS 上での手作業チェックリストです。

- [ ] **Step 1: DNS 追加**

ConoHa（または現在のドメイン管理元）の DNS 管理画面で:
- ホスト: `demo`
- タイプ: A
- 値: 本番 yntools と同じ VPS の IP

伝搬確認:
```bash
dig +short demo.ynfactory.online
```

- [ ] **Step 2: VPS にデモ用チェックアウトを配置**

```bash
ssh <vps-user>@<vps-host>
sudo mkdir -p /opt/yn-tools-demo
sudo chown $USER:$USER /opt/yn-tools-demo
git clone <repo-url> /opt/yn-tools-demo
cd /opt/yn-tools-demo
cp .env.demo.example .env.demo
# SECRET_KEY を openssl rand -hex 32 で生成して書き込む
```

- [ ] **Step 3: Nginx 設定を配置**

```bash
sudo cp docs/operations/demo-nginx.conf.example /etc/nginx/sites-available/demo.ynfactory.online
sudo ln -s /etc/nginx/sites-available/demo.ynfactory.online /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d demo.ynfactory.online
```

- [ ] **Step 4: デモコンテナ起動**

```bash
cd /opt/yn-tools-demo
bash yn-tools/scripts/deploy-demo.sh
```

- [ ] **Step 5: アクセス確認**

ブラウザで `https://demo.ynfactory.online/`:
- デモ説明ページが表示
- 「ツール一覧を見る」→ ダッシュボード表示（ログイン要求なし）
- 任意のツールを開いて動作する
- 料金表記が一切出ない
- 右下に Claude Code バッジ
- 本番 `https://tools.ynfactory.online/` が引き続き正常動作

- [ ] **Step 6: 確認メモを HANDOFF.md に追記してコミット**

```bash
cd "G:/マイドライブ/YNFactory-cc"
# HANDOFF.md (or memory) に「demo.ynfactory.online 稼働中」を追記
git add HANDOFF.md
git commit -m "docs: note demo.ynfactory.online deployment"
```

---

## Task 11: 受け入れチェック（仕様書 §9 と突合）

仕様書 `docs/superpowers/specs/2026-05-04-yntools-seminar-demo-design.md` の §9 を逐一確認:

- [ ] 本番 `tools.ynfactory.online` が従来どおり動作（ログイン・課金・各ツール）
- [ ] `demo.ynfactory.online` がログイン不要で開ける
- [ ] デモ版に料金表記・販売文言が一切表示されない
- [ ] デモ版で全ツールが触れる（課金画面が出ない）
- [ ] 各ページに「Claude Code 開発」バッジが表示
- [ ] デモ版で生成・保存したデータがコンテナ再起動で消える
- [ ] HTTPS 証明書が `demo.ynfactory.online` に発行されている
- [ ] 本番 DB ファイル・本番 uploads がデモコンテナから参照不能（`docker inspect yn-tools-demo` で volumes 空を確認）

全てチェックが入ったら作業完了。
