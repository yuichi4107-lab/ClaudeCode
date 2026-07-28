"""YN Tools - AI業務自動化プラットフォーム"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.templates import make_templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth.dependencies import get_current_user
from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Seed GEMS/GPT library on first startup
    from app.tools.gems.service import seed_gems_items
    from app.database import async_session as _session
    async with _session() as db:
        count = await seed_gems_items(db)
        if count:
            print(f"[startup] Seeded {count} GEMS/GPT items.")

    # Seed tool definitions (upsert by slug — 既存は触らず、未登録slugのみ追加)
    from app.users.models import ToolDefinition
    from sqlalchemy import select
    async with _session() as db:
        result = await db.execute(select(ToolDefinition.slug))
        existing_slugs = {row[0] for row in result.all()}
        tools_all = [
                ToolDefinition(slug="sales", name="営業自動化", description="企業リスト・HP巡回・CRM・メール営業", monthly_price=100, display_order=1, icon_emoji="📼", stripe_product_id="prod_UDDIwP4jsIEPyk", stripe_price_id="price_1TEmrmKAVaivWwqwOO0NPLql"),
                ToolDefinition(slug="mailer", name="メール送信", description="テンプレメール一括送信・履歴管理", monthly_price=100, display_order=2, icon_emoji="✉", stripe_product_id="prod_UDDISonnzcKLmO", stripe_price_id="price_1TEms7KAVaivWwqwabRK9pJb"),
                ToolDefinition(slug="gems", name="GEMS/GPTライブラリ", description="AI業務改善プロンプト200本", monthly_price=100, display_order=3, icon_emoji="✨", stripe_product_id="prod_UDDKTlnnnfoPeR", stripe_price_id="price_1TEmtNKAVaivWwqwmeG7NnWK"),
                ToolDefinition(slug="docai", name="AI文書処理", description="PDF・テキストをAIで要約・翻訳・Q&A・情報抽出", monthly_price=100, display_order=4, icon_emoji="📄", stripe_product_id="prod_UFpGHnbxTIY5Vb", stripe_price_id="price_1THJcFKAVaivWwqwBmYWEkGk"),
                ToolDefinition(slug="contentgen", name="AIコンテンツ生成", description="SNS投稿・ブログ記事・広告コピー・メールをAI自動作成", monthly_price=100, display_order=5, icon_emoji="✍", stripe_product_id="prod_UFpGzK1GN0kShA", stripe_price_id="price_1THJcFKAVaivWwqwzXpOSHHi"),
                ToolDefinition(slug="webresearch", name="AI Webリサーチャー", description="URLを入力→AIがページ分析・要約・競合比較", monthly_price=100, display_order=6, icon_emoji="🔍", stripe_product_id="prod_UFpGoIwul505DJ", stripe_price_id="price_1THJcGKAVaivWwqwtcr2sni6"),
                ToolDefinition(slug="imagegen", name="AI画像生成", description="プロンプトからSNS画像・バナー・商品画像を一括生成", monthly_price=100, display_order=7, icon_emoji="🎨", stripe_product_id="prod_UFpGtItyTPHits", stripe_price_id="price_1THJcHKAVaivWwqwUTmXRKj5"),
                ToolDefinition(slug="chatbot", name="AIチャットボットビルダー", description="自社サイトに埋め込めるAIチャットボットを作成・管理", monthly_price=100, display_order=8, icon_emoji="🤖", stripe_product_id="prod_UFpGDaGFH7tNOo", stripe_price_id="price_1THJcHKAVaivWwqweWxPy8wM"),
                ToolDefinition(slug="qrcode", name="QRコードジェネレーター", description="URL・テキストからQRコードを即座に生成", monthly_price=100, display_order=9, stripe_product_id="prod_UFpGHOqm0BrglG", stripe_price_id="price_1THJcIKAVaivWwqwr5ukmrfk"),
                ToolDefinition(slug="fileconv", name="ファイル変換ツール", description="画像・テキスト・データのフォーマット変換", monthly_price=100, display_order=10, stripe_product_id="prod_UFpGqEJ8vdbp8t", stripe_price_id="price_1THJcIKAVaivWwqwDzjSJM8i"),
                ToolDefinition(slug="taskmanager", name="タスクマネージャー", description="シンプルなタスク・締切管理", monthly_price=100, display_order=11, stripe_product_id="prod_UFpGCIM98v3gKz", stripe_price_id="price_1THJcJKAVaivWwqwwczBGb1n"),
                ToolDefinition(slug="formbuilder", name="フォームビルダー", description="アンケート・申込フォームをノーコード作成", monthly_price=100, display_order=12, stripe_product_id="prod_UFpGsvPZND2Ymc", stripe_price_id="price_1THJcJKAVaivWwqwRpgxFua9"),
                ToolDefinition(slug="invoice", name="請求書ジェネレーター", description="請求書を作成してPDFダウンロード", monthly_price=100, display_order=13, stripe_product_id="prod_UFpGC4r4n2Jndr", stripe_price_id="price_1THJcKKAVaivWwqwjp7WIwZb"),
                ToolDefinition(slug="translate", name="翻訳", description="16言語対応・ビジネス/カジュアル/技術文書の自動翻訳", monthly_price=100, display_order=14, stripe_product_id="prod_UFpGwwmGW1P7A0", stripe_price_id="price_1THJcLKAVaivWwqwcBxODUQA"),
                ToolDefinition(slug="writing", name="ライティングアシスタント", description="文章の校正・リライト・トーン変換を自動処理", monthly_price=100, display_order=15, stripe_product_id="prod_UFpGqgyAEAfyR2", stripe_price_id="price_1THJcLKAVaivWwqwZhTlZRRf"),
                ToolDefinition(slug="contract", name="契約書チェッカー", description="契約書のリスク分析・要約・条項解説を自動実行", monthly_price=100, display_order=16, stripe_product_id="prod_UFpGShVe2fzl76", stripe_price_id="price_1THJcMKAVaivWwqw58ifggpA"),
                ToolDefinition(slug="sns", name="SNS投稿スケジューラー", description="投稿の下書き・スケジュール管理・文案自動生成", monthly_price=100, display_order=17, stripe_product_id="prod_UFpGGMXzJgTUvU", stripe_price_id="price_1THJcMKAVaivWwqwDttQSNwm"),
                ToolDefinition(slug="minutes", name="議事録", description="会議メモから構造化された議事録を自動生成", monthly_price=100, display_order=18, stripe_product_id="prod_UFpGVTxxjoiwzN", stripe_price_id="price_1THJcNKAVaivWwqwCE2AoGux"),
                ToolDefinition(slug="lpbuilder", name="LPビルダー", description="原稿を入力するだけでLPを即公開", monthly_price=100, display_order=19, stripe_product_id="prod_UFpGGLFUnoAy0o", stripe_price_id="price_1THJcNKAVaivWwqwCQ9UxI3K"),
                ToolDefinition(slug="booking", name="予約管理", description="予約フォームを作成して公開URLで予約受付", monthly_price=100, display_order=20, stripe_product_id="prod_UFpGoaaueRhFhM", stripe_price_id="price_1THJcOKAVaivWwqwwZTar1Iu"),
                ToolDefinition(slug="expense", name="経費トラッカー", description="レシートAI読取・カテゴリ分類・月次レポート", monthly_price=100, display_order=21, stripe_product_id="prod_UFpGIJKnbxZy8g", stripe_price_id="price_1THJcPKAVaivWwqwBovu9Jum"),
                ToolDefinition(slug="seocheck", name="SEO分析", description="URLのSEOスコア・問題検出・AI改善提案", monthly_price=100, display_order=22, stripe_product_id="prod_UFpGu4yCl9A8l9", stripe_price_id="price_1THJcPKAVaivWwqwE3U6GUy1"),
                ToolDefinition(slug="salesboard", name="売上ダッシュボード", description="売上入力・グラフ可視化・月次推移・目標管理", monthly_price=100, display_order=23, stripe_product_id="prod_UFpGttLAa7oHML", stripe_price_id="price_1THJcQKAVaivWwqwHXHppCs6"),
                ToolDefinition(slug="estimate", name="見積書作成", description="見積書を作成してPDFダウンロード", monthly_price=100, display_order=24, stripe_product_id="prod_UFpGm9vlzDCClC", stripe_price_id="price_1THJcQKAVaivWwqwU97UuRkZ"),
                ToolDefinition(slug="passgen", name="パスワード生成", description="安全なパスワード生成・強度チェック", monthly_price=100, display_order=25, stripe_product_id="prod_UFpGMrmQoKuDjb", stripe_price_id="price_1THJcRKAVaivWwqwvSkLKyyk"),
                ToolDefinition(slug="dailyreport", name="日報ジェネレーター", description="作業メモからAIで日報・週報を自動生成", monthly_price=100, display_order=26, stripe_product_id="prod_UFpG0ji2usZ6cK", stripe_price_id="price_1THJcSKAVaivWwqw1fDV6w0J"),
                ToolDefinition(slug="cardreader", name="名刺リーダー", description="名刺画像→AI-OCR→連絡先データ化・CSV出力", monthly_price=100, display_order=27, stripe_product_id="prod_UFpHLtstUov7OI", stripe_price_id="price_1THJcSKAVaivWwqwRq9zzV2P"),
                ToolDefinition(slug="voiceminutes", name="AI議事メモ（音声）", description="音声ファイル→文字起こし→議事録を自動生成", monthly_price=100, display_order=28, stripe_product_id="prod_UFpHU0WoyqXQtr", stripe_price_id="price_1THJcTKAVaivWwqwMUjyABc9"),
                ToolDefinition(slug="mdviewer", name="Markdownビューアー", description="Markdownファイルを美しくレンダリング表示・PDF出力", monthly_price=100, display_order=29, icon_emoji="📝", stripe_product_id="prod_UHJeSny8oNDQ1Z", stripe_price_id="price_1TIl1PKAVaivWwqw8micL2QE"),
                ToolDefinition(slug="clipboard", name="クリップボード共有", description="PC⇔スマホ間でテキストをリアルタイム共有", monthly_price=100, display_order=30, icon_emoji="📋", stripe_product_id="prod_UHOTW4sIEZbnrj", stripe_price_id="price_1TIpgHKAVaivWwqwORmVyHaC"),
                ToolDefinition(slug="shift", name="シフト作成", description="従業員シフト表の作成・AI自動生成・Excel出力", monthly_price=100, display_order=31, icon_emoji="📅", stripe_product_id="prod_UJ5Mt8j7by3gW5", stripe_price_id="price_1TKTBdKAVaivWwqwC4aMDZLk"),
                ToolDefinition(slug="jobposting", name="求人票ジェネレーター", description="9業種テンプレートから Indeed/タウンワーク/ハローワーク形式の求人票をAI生成", monthly_price=100, display_order=32, icon_emoji="📋", stripe_product_id="prod_UKKGmqY48PCrmt", stripe_price_id="price_1TLfcDKAVaivWwqwl46KM8C5"),
                ToolDefinition(slug="dataclean", name="データクリーニング", description="CSV/Excelの重複削除・表記揺れ統一・差分プレビュー", monthly_price=100, display_order=33, icon_emoji="🧹", stripe_product_id="prod_UKKGIIaDu8YNgZ", stripe_price_id="price_1TLfcEKAVaivWwqwY0gFaph5"),
                ToolDefinition(slug="imgbatch", name="画像一括加工", description="D&DでSNS9プリセットリサイズ・背景除去・ZIP一括ダウンロード", monthly_price=100, display_order=34, icon_emoji="🖼️", stripe_product_id="prod_UKKGLbx6ywjE7J", stripe_price_id="price_1TLfcEKAVaivWwqw3OwnDNg5"),
                ToolDefinition(slug="stepmail", name="ステップメール作成", description="8種ビジネス目的からシリーズをAI一括生成・個別編集", monthly_price=100, display_order=35, icon_emoji="📨", stripe_product_id="prod_UKKGyRIRa8KfMd", stripe_price_id="price_1TLfcFKAVaivWwqwJUuTuIjw"),
                ToolDefinition(slug="legalgen", name="契約書・利用規約自動作成", description="7種の契約書/利用規約をAI生成。Word/PDF出力対応", monthly_price=100, display_order=36, icon_emoji="⚖️", stripe_product_id="prod_UKKGM9lrOnEbOe", stripe_price_id="price_1TLfcGKAVaivWwqw2CsdiFQu"),
                ToolDefinition(slug="epubcheck", name="EPUBバリデーター", description="KDP出版前の EPUB 破損・規格違反・表紙・フォントを即時チェック", monthly_price=100, display_order=37, icon_emoji="📚", stripe_product_id="prod_UQQ6dAhplgZn31", stripe_price_id="price_1TRZG2KAVaivWwqw3aVVjJSd"),
        ]
        new_tools = [t for t in tools_all if t.slug not in existing_slugs]
        if new_tools:
            db.add_all(new_tools)
            await db.commit()
            print(f"[startup] Seeded {len(new_tools)} tool definitions: {[t.slug for t in new_tools]}")

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Session middleware (signed cookie for auth)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.users.router import router as users_router
from app.tools.mailer.router import router as mailer_router
from app.tools.gems.router import router as gems_router
from app.tools.sales.router import router as sales_router
from app.community.router import router as community_router
from app.tools.docai.router import router as docai_router
from app.tools.contentgen.router import router as contentgen_router
from app.tools.webresearch.router import router as webresearch_router
from app.tools.imagegen.router import router as imagegen_router
from app.tools.chatbot.router import router as chatbot_router
from app.tools.qrcode.router import router as qrcode_router
from app.tools.fileconv.router import router as fileconv_router
from app.tools.taskmanager.router import router as taskmanager_router
from app.tools.formbuilder.router import router as formbuilder_router
from app.tools.invoice.router import router as invoice_router
from app.tools.translate.router import router as translate_router
from app.tools.writing.router import router as writing_router
from app.tools.contract.router import router as contract_router
from app.tools.sns.router import router as sns_router
from app.tools.minutes.router import router as minutes_router
from app.tools.lpbuilder.router import router as lpbuilder_router
from app.tools.booking.router import router as booking_router
from app.tools.expense.router import router as expense_router
from app.tools.seocheck.router import router as seocheck_router
from app.tools.salesboard.router import router as salesboard_router
from app.tools.estimate.router import router as estimate_router
from app.tools.passgen.router import router as passgen_router
from app.tools.dailyreport.router import router as dailyreport_router
from app.tools.cardreader.router import router as cardreader_router
from app.tools.voiceminutes.router import router as voiceminutes_router
from app.tools.mdviewer.router import router as mdviewer_router
from app.tools.clipboard.router import router as clipboard_router
from app.tools.shift.router import router as shift_router
from app.tools.jobposting.router import router as jobposting_router
from app.tools.dataclean.router import router as dataclean_router
from app.tools.imgbatch.router import router as imgbatch_router
from app.tools.stepmail.router import router as stepmail_router
from app.tools.legalgen.router import router as legalgen_router
from app.tools.epubcheck.router import router as epubcheck_router
from app.admin.router import router as admin_router

app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(users_router)
app.include_router(mailer_router)
app.include_router(gems_router)
app.include_router(sales_router)
app.include_router(docai_router)
app.include_router(contentgen_router)
app.include_router(webresearch_router)
app.include_router(imagegen_router)
app.include_router(chatbot_router)
app.include_router(qrcode_router)
app.include_router(fileconv_router)
app.include_router(taskmanager_router)
app.include_router(formbuilder_router)
app.include_router(invoice_router)
app.include_router(translate_router)
app.include_router(writing_router)
app.include_router(contract_router)
app.include_router(sns_router)
app.include_router(minutes_router)
app.include_router(lpbuilder_router)
app.include_router(booking_router)
app.include_router(expense_router)
app.include_router(seocheck_router)
app.include_router(salesboard_router)
app.include_router(estimate_router)
app.include_router(passgen_router)
app.include_router(dailyreport_router)
app.include_router(cardreader_router)
app.include_router(voiceminutes_router)
app.include_router(mdviewer_router)
app.include_router(clipboard_router)
app.include_router(shift_router)
app.include_router(jobposting_router)
app.include_router(dataclean_router)
app.include_router(imgbatch_router)
app.include_router(stepmail_router)
app.include_router(legalgen_router)
app.include_router(epubcheck_router)
# display_order=32 (jobposting), 33 (dataclean), 34 (imgbatch), 35 (stepmail), 36 (legalgen), 37 (epubcheck) - ToolDefinition シードは Stripe Price ID 確定後に追加
app.include_router(community_router)
app.include_router(admin_router)

templates = make_templates("app/templates")


@app.get("/guide", response_class=HTMLResponse)
async def guide(request: Request, user=Depends(get_current_user)):
    """使い方ガイドページ"""
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)
    return templates.TemplateResponse(
        request, "guide.html", {"user": user, "page": "guide"}
    )


@app.get("/health")
async def health_check():
    """Health check for Render monitoring."""
    from sqlalchemy import text
    from app.database import async_session
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return JSONResponse({"status": "ok", "db": "connected"})
    except Exception as e:
        return JSONResponse({"status": "error", "db": str(e)}, status_code=503)


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request, user=Depends(get_current_user)):
    """Landing page (top) or redirect to dashboard if logged in."""
    if settings.demo_mode:
        from fastapi.responses import RedirectResponse
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


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(get_current_user)):
    """Dashboard page."""
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/auth/login", status_code=303)

    # 個別ツール購読中のslug一覧を取得
    # is_active=True OR 削除予約中（canceled_at が未来）のツールも含む
    subscribed_tools: set[str] = set()
    if user.plan == "per_tool":
        from datetime import datetime as _dt
        from sqlalchemy import or_, and_, select
        from app.database import get_db as _get_db
        from app.database import async_session
        from app.users.models import UserToolSubscription
        async with async_session() as db:
            result = await db.execute(
                select(UserToolSubscription.tool_slug).where(
                    UserToolSubscription.user_id == user.id,
                    or_(
                        UserToolSubscription.is_active == True,
                        and_(
                            UserToolSubscription.canceled_at != None,
                            UserToolSubscription.canceled_at > _dt.utcnow(),
                        ),
                    ),
                )
            )
            subscribed_tools = {row[0] for row in result.all()}

    # Stripeサブスクリプション情報（有効期間・自動更新）
    subscription_info = None
    if user.stripe_subscription_id:
        from app.users.router import _get_subscription_info
        subscription_info = _get_subscription_info(user.stripe_subscription_id)

    # Free期間中の有料開始日（trial_ends_atの翌日）
    paid_start_date = None
    if user.is_in_trial and user.trial_ends_at:
        from datetime import timedelta as _td
        paid_start = (user.trial_ends_at + _td(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        paid_start_date = paid_start.strftime("%Y年%m月%d日")

    return templates.TemplateResponse(
        request, "dashboard.html", {
            "user": user,
            "page": "dashboard",
            "subscribed_tools": subscribed_tools,
            "subscription_info": subscription_info,
            "paid_start_date": paid_start_date,
        }
    )
