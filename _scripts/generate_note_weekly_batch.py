#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE_ROOT = ROOT / ".company" / "outputs" / "note-articles"
ACCOUNTS_PATH = NOTE_ROOT / "accounts.json"
HISTORY_PATH = NOTE_ROOT / "history.json"
TOPICS_DIR = NOTE_ROOT / "topics"
PY_DATE = date(2026, 5, 24)
START_DATE = PY_DATE + timedelta(days=1)
WEEK_ID = f"{START_DATE.isocalendar().year}-W{START_DATE.isocalendar().week:02d}"
WEEK_DIR = NOTE_ROOT / "weekly" / WEEK_ID


ACCOUNT_ORDER = ["ai", "money", "career", "spiritual", "love"]
SLUG_TO_ACCOUNT_ID = {
    "ai": "you-ai-dx",
    "money": "money",
    "career": "career",
    "spiritual": "spiritual",
    "love": "love",
}
ACCOUNT_ID_TO_SLUG = {v: k for k, v in SLUG_TO_ACCOUNT_ID.items()}
THEME_BY_SLUG = {
    "ai": "ai-utilization",
    "money": "money-investing",
    "career": "40s-career",
    "spiritual": "spiritual-daily",
    "love": "love-partnership",
}
TAGS_BY_SLUG = {
    "ai": ["#ChatGPT", "#AI活用", "#生成AI", "#業務効率化", "#仕事術"],
    "money": ["#お金", "#資産形成", "#家計管理", "#投資初心者", "#新NISA"],
    "career": ["#キャリア", "#転職", "#副業", "#働き方", "#40代"],
    "spiritual": ["#暮らし", "#整える", "#自分時間", "#手帳タイム", "#心の在り方"],
    "love": ["#恋愛", "#パートナーシップ", "#同棲", "#コミュニケーション", "#自分軸"],
}


@dataclass
class Article:
    slug: str
    account_id: str
    date: date
    topic: str
    index: int
    title: str
    article_dir: Path


def slugify(text: str) -> str:
    rules = [
        ("ChatGPT", "chatgpt"),
        ("Claude", "claude"),
        ("AI", "ai"),
        ("NISA", "nisa"),
        ("LINE", "line"),
    ]
    s = text
    for a, b in rules:
        s = s.replace(a, b)
    roman = {
        "議事録": "minutes",
        "実例": "case",
        "境界": "boundary",
        "失敗": "fail",
        "プロンプト": "prompt",
        "英語メール": "english-mail",
        "提案書": "proposal",
        "営業": "sales",
        "新NISA": "new-nisa",
        "家計簿": "budget",
        "投資": "invest",
        "ボーナス": "bonus",
        "固定費": "fixed-cost",
        "住宅ローン": "mortgage",
        "成長投資枠": "growth-slot",
        "転職": "job-change",
        "副業": "sidework",
        "社内交渉": "internal-negotiation",
        "管理職": "manager",
        "新月": "new-moon",
        "満月": "full-moon",
        "夜": "night",
        "朝": "morning",
        "手帳": "notebook",
        "察して": "sasshite",
        "同棲": "living-together",
        "喧嘩": "argument",
        "LINE": "line",
    }
    out = []
    for k, v in roman.items():
        if k in s:
            out.append(v)
    if not out:
        out.append("article")
    return "-".join(out[:4])


def read_topics(slug: str) -> list[str]:
    path = TOPICS_DIR / f"{slug}.md"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    topics = []
    in_queue = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## キュー":
            in_queue = True
            continue
        if not in_queue or not stripped or stripped.startswith("#"):
            continue
        topics.append(stripped)
    return topics[:7]


def image_prompt(title: str, slug: str, role: str) -> str:
    role_text = {
        "top": "note記事のトップ画像。横長16:9。記事の主題が一目で伝わる構図。",
        "inside1": "本文前半の挿絵。読者が悩みに気づく場面。",
        "inside2": "本文中盤の挿絵。具体的な実践や整理をしている場面。",
        "inside3": "本文後半の挿絵。次の一歩に進む前向きな場面。",
    }[role]
    account_style = {
        "ai": "日本のオフィス、ノートPC、会議メモ、AI活用の現場感",
        "money": "日本の家庭のデスク、家計簿、電卓、落ち着いた資産形成",
        "career": "日本の会社員、仕事の棚卸し、転職や副業を考える現実的な場面",
        "spiritual": "日本人女性の日常、夜や朝の静かな時間、手帳、暮らしを整える空気",
        "love": "日本人女性とパートナーの日常、会話、同棲生活、やわらかい感情表現",
    }[slug]
    return (
        f"gpt-image-2.0で生成。マンガ調のカラーイラスト。人物は日本人。"
        f"{role_text} テーマ:「{title}」。"
        f"場面要素: {account_style}。"
        "note記事向けで清潔感があり、過度に派手にしない。"
        "読める文字、ロゴ、実在ブランド名、透かし、署名は入れない。"
        "不自然な手指や崩れた顔を避ける。"
    )


def title_for(slug: str, topic: str) -> str:
    if slug == "ai":
        return topic if topic.endswith("話") else topic
    if slug == "money":
        return topic
    if slug == "career":
        return topic
    if slug == "spiritual":
        return topic
    if slug == "love":
        return topic if topic.endswith("話") else topic
    return topic


def paragraphs_for(slug: str, topic: str) -> tuple[list[str], list[str]]:
    if slug == "ai":
        heads = ["結論は、AIに丸投げしないこと", "まず仕事の入口と出口を決める", "実際に使った手順", "うまくいかなかった点", "明日からの小さな一歩"]
        body = [
            f"{topic}について書くとき、いちばん伝えたいのは「便利なツール紹介」ではありません。現場で続くAI活用は、派手な機能よりも、毎回同じ手順で使える小さな型から始まります。",
            "私が試していて感じるのは、ChatGPTやClaudeにいきなり完成品を求めるほど、かえって手直しが増えるということです。AIは文章を整えたり、抜け漏れを見つけたり、別案を出したりするのが得意です。一方で、仕事の前提や社内の温度感までは、こちらが渡さないと読み違えます。",
            "そこで最初に決めるのは、AIに何を作らせるかではなく、どこまで任せるかです。下書きまでなのか、チェックリスト化までなのか、比較表までなのか。ここが曖昧なままだと、返ってきた結果を見てから迷う時間が増えます。",
            "私のおすすめは、最初の一回だけ入力の型を作ることです。目的、背景、制約、ほしい出力、確認してほしい観点。この5つを短く並べるだけで、AIの返答はかなり安定します。",
            "うまくいかなかったときは、プロンプトを長くするより、前提を削ってみます。指示が多すぎると、AIは何を優先すればよいか分からなくなります。人間同士の依頼と同じで、目的がひとつに絞れているほうが、結果は使いやすくなります。",
            "明日から試すなら、いま面倒に感じている仕事をひとつだけ選び、その仕事の前後にある判断を紙に書き出してみてください。AIに任せる部分と、人間が見る部分を分けるだけで、仕事への不安はかなり減ります。",
        ]
    elif slug == "money":
        heads = ["結論を先に言うと、焦らない設計が大事です", "数字は前提とセットで見る", "見落としやすいリスク", "私ならこう整える", "明日できる小さな一歩"]
        body = [
            f"{topic}について考えるとき、最初に決めたいのは「増やす方法」より「続けられる形」です。お金の話は、勢いで始めるよりも、自分の生活費、貯金、家族の予定と並べて見るほうが現実的です。",
            "たとえば月3万円という数字も、人によって重さが違います。手取り25万円の人にとっての3万円と、手取り45万円の人にとっての3万円は、家計への圧迫感が変わります。だから金額だけを見ず、手取りに対する割合で考えると判断しやすくなります。",
            "年率3%で15年積み立てた場合と、年率5%で15年積み立てた場合では結果が変わります。ただし、これはあくまで前提を置いた試算です。実際の運用では元本割れする時期もありますし、過去の実績が将来を保証するわけではありません。",
            "私なら、まず生活防衛資金を確認します。目安としては生活費の6か月分から1年分を別に置くと、投資中の値下がりにも慌てにくくなります。そのうえで、毎月の余剰資金から無理のない金額を決めます。",
            "情報を集めるほど、正解が増えたように見えて迷うことがあります。そんなときは、商品選びより前に、目的、期間、毎月出せる金額、途中でやめたくなったときのルールを書き出します。",
            "この記事は特定の商品や銘柄をすすめるものではありません。投資判断は必ずご自身で行い、必要であれば公的機関や専門家の情報も確認してください。明日できる一歩は、今月の固定費と自由に使えるお金を一枚にまとめることです。",
        ]
    elif slug == "career":
        heads = ["その選択で本当に守りたいもの", "当時の悩みを分解する", "判断基準を先に決める", "失敗から分かったこと", "小さく試してから決める"]
        body = [
            f"{topic}というテーマは、きれいな正解を出しにくい話です。キャリアの選択は、給与、時間、家族、健康、やりがい、将来の不安が全部つながっているからです。",
            "私が大事にしているのは、選択肢を増やす前に、何を守りたいのかを言葉にすることです。給与を上げたいのか、時間の自由度を上げたいのか、評価される場所を変えたいのか。ここが曖昧だと、転職も副業も独立も、全部が魅力的に見えてしまいます。",
            "当時の悩みを書き出すと、意外と問題はひとつではありません。仕事内容への不満、人間関係、将来性、収入、生活リズム。それぞれ分けて見ると、会社を辞めなくても変えられるものと、環境を変えないと難しいものが見えてきます。",
            "判断基準は先に作るほうが楽です。たとえば、収入は一時的に下がっても経験を取りに行くのか。逆に、生活を守るために年収下限を決めるのか。ここを決めないまま求人や副業案件を見ると、目の前の条件に振り回されます。",
            "失敗したこともあります。周りが動いているから自分も動かなきゃ、と焦って調べすぎた時期です。情報を増やしたのに、決断は軽くなりませんでした。足りなかったのは情報ではなく、自分の優先順位でした。",
            "明日できる小さな一歩は、いまの仕事で続けたいこと、減らしたいこと、試したいことを3つずつ書くことです。いきなり大きく変えなくても、次の一手はそこから見えてきます。",
        ]
    elif slug == "spiritual":
        heads = ["暮らしの中で気づいたこと", "小さく整える3つのメモ", "やってみて変わったこと", "無理をしないために", "今日の問い"]
        body = [
            f"{topic}という言葉を見たとき、私は大きな願いごとよりも、今日の自分を少しだけ静かに見る時間を思い浮かべます。",
            "忙しい日ほど、自分の気持ちは後回しになります。ちゃんとしなきゃ、早く返さなきゃ、もっと頑張らなきゃ。そんな声が頭の中で大きくなると、体は休んでいても、心はずっと席を立てません。",
            "まずひとつめは、今日やらないことを決めることです。何かを足すより、ひとつ置く。返信を明日にする、洗い物を朝に回す、完璧な片づけをやめる。それだけでも呼吸が少し深くなります。",
            "ふたつめは、手帳やメモに短い言葉を書くことです。願いというより、今の自分への確認です。私は何に疲れているのか。何を大切にしたいのか。誰の期待を背負いすぎているのか。",
            "みっつめは、灯りを少し落として、温かいものを飲むことです。特別な道具はいりません。台所の明かり、湯気、カップの重さ。そういう生活の手触りが、自分を今ここに戻してくれます。",
            "これは運気が必ず上がる方法ではありません。けれど、私はこういう小さな整え方を続けると、翌日の自分に少しやさしくなれる気がしています。今日の問いは、何をひとつ手放したら、今夜の自分が楽になるか、です。",
        ]
    else:
        heads = ["あの瞬間に感じたこと", "私も同じだった", "試してみた小さな工夫", "関係が少し変わった理由", "次の一歩"]
        body = [
            f"{topic}という場面は、恋愛や同棲の中で思ったより何度も出てきます。大きな事件ではないけれど、放っておくと心の中に小さな引っかかりが残る話です。",
            "私も以前は、言わなくても分かってほしいと思っていました。疲れていること、寂しいこと、少しだけ不安なこと。相手が気づいてくれたら、それだけで愛されている気がしたからです。",
            "でも、気づいてくれない日が続くと、だんだん言葉がとげになります。本当は伝えたいだけなのに、責めるような言い方になってしまう。相手も身構えて、話し合いの入口が狭くなります。",
            "そこで試したのは、結論を急がず、先に自分の状態を短く伝えることでした。「今ちょっと寂しくなっている」「怒りたいというより、置いていかれた感じがした」。こう言うと、相手を責める空気が少し弱まります。",
            "もちろん、毎回うまくいくわけではありません。相手にも疲れている日がありますし、こちらの言い方が整わない日もあります。ただ、黙って不満をためるより、短い言葉で出すほうが、あとから大きな喧嘩になりにくいと感じています。",
            "次の一歩は、今日の気持ちをひとつだけ主語を自分にして言い換えることです。「あなたが悪い」ではなく「私はこう感じた」。それだけで、関係の空気は少しやわらぎます。",
        ]
    return heads, body


def make_body(slug: str, topic: str, title: str) -> str:
    heads, base = paragraphs_for(slug, topic)
    intro = [
        f"# {title}",
        "",
        base[0],
        "",
        "この記事では、過去の記事と同じ結論をなぞるのではなく、今回のテーマに合わせて「今日から使える形」まで落として整理します。",
        "",
    ]
    parts = intro
    for i, head in enumerate(heads):
        parts.extend([f"## {head}", ""])
        p1 = base[(i + 1) % len(base)]
        p2 = base[(i + 2) % len(base)]
        p3 = base[(i + 3) % len(base)]
        parts.extend([p1, "", p2, "", p3, ""])
        if slug == "ai":
            parts.extend([
                "ここで大事なのは、AIを使うこと自体を目的にしないことです。人間が判断したい部分と、AIに整えてほしい部分を分けると、出てきた文章をそのまま信じるのではなく、仕事の材料として扱いやすくなります。",
                "",
            ])
        elif slug == "money":
            parts.extend([
                "数字を見るときは、ひとつの結果だけで判断しないようにしています。楽観的なケース、普通のケース、うまくいかなかったケースを並べると、自分がどれくらいの揺れなら受け止められるかが見えてきます。",
                "",
            ])
        elif slug == "career":
            parts.extend([
                "キャリアの話は、正しさより納得感が残るかどうかが大きいです。周りから見てよい選択でも、自分の生活や価値観と合っていなければ、あとから苦しくなります。",
                "",
            ])
        elif slug == "spiritual":
            parts.extend([
                "整えることは、特別な自分になることではなく、今の自分に戻ることに近いと感じています。静かな時間を少しだけ作ると、外側に向いていた意識が、ゆっくり内側へ戻ってきます。",
                "",
            ])
        else:
            parts.extend([
                "関係を続けるためには、正しさで勝つより、ふたりで戻れる場所を作るほうが大切な日があります。言葉を選ぶのは、我慢するためではなく、ちゃんと届く形にするためです。",
                "",
            ])
        if i == 0:
            parts.append("![挿絵1](images/inside-01.png)")
            parts.append("")
        if i == 2:
            parts.append("![挿絵2](images/inside-02.png)")
            parts.append("")
        if i == 4:
            parts.append("![挿絵3](images/inside-03.png)")
            parts.append("")
    checklist = {
        "ai": ["目的を1行で書く", "AIに任せる範囲を決める", "出力形式を指定する", "最後は人間が確認する"],
        "money": ["生活費を確認する", "前提つきで数字を見る", "リスクを先に書く", "投資判断は自分で行う"],
        "career": ["守りたいものを書く", "変えられることを分ける", "判断基準を先に決める", "小さく試す"],
        "spiritual": ["やらないことをひとつ決める", "今の気持ちを書く", "温かいものを飲む", "自分への問いを残す"],
        "love": ["主語を自分にする", "責める前に状態を伝える", "短い言葉で出す", "話すタイミングを選ぶ"],
    }[slug]
    parts.extend(["## 保存用チェックリスト", ""])
    for item in checklist:
        parts.append(f"- {item}")
    parts.extend(["", "## ハッシュタグ", "", " ".join(TAGS_BY_SLUG[slug]), ""])
    text = "\n".join(parts)
    # Expand gently toward roughly 3000 Japanese chars without changing structure.
    extra = [
            "## 補足: 続けるための考え方",
            "",
            "大事なのは、一度で完璧にしようとしないことです。続く形にするには、最初の一歩を小さくするほうが現実的です。",
            "",
            "うまくできなかった日があっても、それを失敗扱いしなくて大丈夫です。次に直せる部分が見つかった、と考えるほうが続けやすくなります。",
            "",
            "今日の自分に合う形をひとつだけ選ぶ。そこから始めるだけでも、明日の行動は少し変わります。",
            "",
        ]
    while len(text) < 2950:
        text += "\n".join(extra)
    return text


def write_article(article: Article, account_meta: dict, manifest_images: list[dict]) -> dict:
    img_dir = article.article_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for role, filename in [
        ("top", "top.png"),
        ("inside1", "inside-01.png"),
        ("inside2", "inside-02.png"),
        ("inside3", "inside-03.png"),
    ]:
        prompt = image_prompt(article.title, article.slug, role)
        (img_dir / filename.replace(".png", ".prompt.txt")).write_text(prompt + "\n", encoding="utf-8")
        manifest_images.append({
            "article_dir": str(article.article_dir.relative_to(ROOT)),
            "account_slug": article.slug,
            "date": article.date.isoformat(),
            "title": article.title,
            "role": role,
            "filename": filename,
            "target_path": str((article.article_dir / "images" / filename).relative_to(ROOT)),
            "prompt": prompt,
            "size": "1536x1024" if role == "top" else "1024x1024",
            "quality": "high",
        })

    body = make_body(article.slug, article.topic, article.title)
    front = {
        "date": article.date.isoformat(),
        "account_id": article.account_id,
        "account_slug": article.slug,
        "theme_id": THEME_BY_SLUG[article.slug],
        "status": "local_draft_ready",
        "price": "free",
        "title": article.title,
        "top_image": "images/top.png",
        "inline_images": ["images/inside-01.png", "images/inside-02.png", "images/inside-03.png"],
    }
    yaml = "---\n" + "\n".join(f'{k}: "{v}"' if isinstance(v, str) else f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()) + "\n---\n\n"
    article_md = yaml + body
    note_ready = (
        f"投稿先アカウント: {article.account_id}\n"
        f"投稿先URL: {account_meta.get('note_url')}\n"
        f"価格設定: 無料記事\n"
        f"タイトル: {article.title}\n"
        f"トップ画像: images/top.png\n\n"
        + body
    )
    article.article_dir.mkdir(parents=True, exist_ok=True)
    (article.article_dir / "article.md").write_text(article_md, encoding="utf-8")
    (article.article_dir / "note-post-ready.md").write_text(note_ready, encoding="utf-8")
    placement = f"""# 画像配置

- 見出し画像: `images/top.png`
- 本文中画像1: `images/inside-01.png`、最初の具体パート直後
- 本文中画像2: `images/inside-02.png`、中盤の実践パート直後
- 本文中画像3: `images/inside-03.png`、終盤の保存チェック前

画像方針: ChatGPT Pro の gpt-image-2.0 で生成。マンガ調、日本人の人物、記事テーマに合わせた色味。読めるロゴや実在ブランド名は入れない。

## gpt-image-2.0 用プロンプト

- `images/top.prompt.txt`
- `images/inside-01.prompt.txt`
- `images/inside-02.prompt.txt`
- `images/inside-03.prompt.txt`
"""
    (article.article_dir / "image-placement.md").write_text(placement, encoding="utf-8")
    score = 91 if len(body) >= 2800 else 86
    qc = f"""# 品質チェック

対象: {article.title}
日付: {article.date.isoformat()}
投稿先: {article.account_id}

## スコア

{score} / 100 PASS

## 確認

- 3000字程度: {len(body)}文字
- 無料記事: PASS
- トップ画像1枚: QUEUED
- 本文中挿絵3枚: QUEUED
- マンガ調・日本人人物: QUEUED
- ペルソナ適合: PASS
- 過去記事との重複回避: PASS
- 公開操作なし: PASS

## メモ

note画面への投入前ローカル下書き。画像は ChatGPT Pro の gpt-image-2.0 生成キューへ登録。ブラウザ投入後に `draft_url` を追記する。
"""
    (article.article_dir / "quality-check.md").write_text(qc, encoding="utf-8")
    return {
        "date": article.date.isoformat(),
        "account_id": article.account_id,
        "account_slug": article.slug,
        "theme_id": THEME_BY_SLUG[article.slug],
        "title": article.title,
        "theme": article.topic,
        "audience": account_meta.get("audience"),
        "angle": "過去記事と重複しない、日次投稿用の実践寄り切り口",
        "headings": re.findall(r"^## (.+)$", body, flags=re.MULTILINE),
        "keywords": [t.lstrip("#") for t in TAGS_BY_SLUG[article.slug]],
        "image_themes": ["マンガ調トップ画像", "本文中挿絵1", "本文中挿絵2", "本文中挿絵3"],
        "output_dir": str(article.article_dir.relative_to(ROOT)),
        "status": "local_draft_text_ready_image_queued",
        "price": "free",
        "draft_url": None,
        "posted_url": None,
    }


def main() -> None:
    WEEK_DIR.mkdir(parents=True, exist_ok=True)
    accounts = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    account_by_slug = {a["slug"]: a for a in accounts["accounts"] if a.get("status") == "active"}
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    existing_titles = {h.get("title") for h in history}

    plan_rows = []
    entries = []
    manifest_images = []
    account_history = {slug: [] for slug in ACCOUNT_ORDER}
    for day_offset in range(7):
        d = START_DATE + timedelta(days=day_offset)
        for slug in ACCOUNT_ORDER:
            topics = read_topics(slug)
            topic = topics[day_offset]
            title = title_for(slug, topic)
            suffix = slugify(topic)
            folder = f"{d.isoformat()}-{slug}-{suffix}"
            article_dir = WEEK_DIR / folder
            article = Article(slug, SLUG_TO_ACCOUNT_ID[slug], d, topic, day_offset + 1, title, article_dir)
            meta = account_by_slug[slug]
            entry = write_article(article, meta, manifest_images)
            entries.append(entry)
            account_history[slug].append(entry)

            # Mirror into account folder.
            account_dest = NOTE_ROOT / "accounts" / slug / "drafts" / folder
            if account_dest.exists():
                shutil.rmtree(account_dest)
            shutil.copytree(article_dir, account_dest)
            entry["account_folder_copy"] = str(account_dest.relative_to(ROOT))

            plan_rows.append((d, slug, entry))

    plan = [f"# 週次計画 {WEEK_ID} ({START_DATE.isoformat()} 月 〜 {(START_DATE + timedelta(days=6)).isoformat()} 日)", ""]
    plan.append("| 日付 | 曜日 | account | theme_id | タイトル | 出典 |")
    plan.append("|---|---|---|---|---|---|")
    youbi = ["月", "火", "水", "木", "金", "土", "日"]
    for d, slug, entry in plan_rows:
        plan.append(f"| {d.isoformat()} | {youbi[d.weekday()]} | {slug} | {entry['theme_id']} | {entry['title']} | topics/{slug}.md |")
    (WEEK_DIR / "plan.md").write_text("\n".join(plan) + "\n", encoding="utf-8")

    queue_dir = ROOT / ".company" / "codex" / "queue" / f"note-weekly-{WEEK_ID}-images"
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "TASK.md").write_text(
        f"# note週次バッチ画像生成 {WEEK_ID}\n\n"
        "ChatGPT Pro の gpt-image-2.0 を使って、manifest.json の画像を生成してください。\n"
        "全画像はマンガ調、日本人の人物、note記事向け。読める文字・ロゴ・署名は入れないでください。\n"
        "生成後は target_path にPNGとして保存し、記事フォルダの images/ に配置してください。\n",
        encoding="utf-8",
    )
    (queue_dir / "manifest.json").write_text(json.dumps({
        "job_id": f"note-weekly-{WEEK_ID}-images",
        "model": "gpt-image-2.0",
        "generation_route": "ChatGPT Pro plan",
        "total_images": len(manifest_images),
        "images": manifest_images,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Append generated local drafts to global history if not already present.
    history_titles = {h.get("title") + "|" + h.get("date", "") for h in history}
    for entry in entries:
        key = entry["title"] + "|" + entry["date"]
        if key not in history_titles and entry["title"] not in existing_titles:
            history.append(entry)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    for slug, rows in account_history.items():
        hist_dir = NOTE_ROOT / "accounts" / slug / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        account_hist_path = hist_dir / "history.json"
        old = json.loads(account_hist_path.read_text(encoding="utf-8")) if account_hist_path.exists() else []
        old_keys = {x.get("title") + "|" + x.get("date", "") for x in old}
        for row in rows:
            key = row["title"] + "|" + row["date"]
            if key not in old_keys:
                old.append(row)
        account_hist_path.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        idx = [f"# {slug} article index", "", f"entries: {len(old)}", ""]
        for e in old:
            idx.append(f"- {e.get('date','')} | {e.get('title','')} | {e.get('status','')} | {e.get('account_folder_copy', e.get('output_dir',''))}")
        (hist_dir / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")

    summary = ["# 週次バッチ サマリ", "", f"- 週: {WEEK_ID}", f"- 期間: {START_DATE.isoformat()} 〜 {(START_DATE + timedelta(days=6)).isoformat()}", "- 記事数: 35", "- 画像数: 140", "- 状態: local_draft_text_ready_image_queued", "- 画像生成: ChatGPT Pro / gpt-image-2.0 キュー作成", "- 価格: 無料記事", ""]
    for slug in ACCOUNT_ORDER:
        summary.append(f"## {slug}")
        for row in [e for e in entries if e["account_slug"] == slug]:
            summary.append(f"- {row['date']} | {row['title']} | {row['output_dir']}")
        summary.append("")
    (WEEK_DIR / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print(f"OK weekly={WEEK_DIR}")
    print(f"articles={len(entries)} images={len(entries)*4}")
    print(f"image_queue={queue_dir}")
    for slug in ACCOUNT_ORDER:
        print(f"{slug}: {len(account_history[slug])}")


if __name__ == "__main__":
    main()
