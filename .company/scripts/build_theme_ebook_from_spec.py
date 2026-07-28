#!/usr/bin/env python3
"""Build a nonfiction theme-to-ebook manuscript package from a book spec.

The builder deliberately stops before image, cover, and EPUB generation.  It
creates the research, planning, manuscript, image-plan, and KDP metadata files
needed by the next stages, and uses validate_ebook_batch.visible_text for the
same 95,000--105,000 character gate as the batch validator.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Callable

from validate_ebook_batch import (
    EXPECTED_MANUSCRIPTS,
    duplicate_long_paragraphs,
    sentence_repetition_metrics,
    validate_book,
    visible_text,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = ROOT / ".company" / "outputs" / "ebooks"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
INTRO_TARGET = 3_000
CHAPTER_TARGET = 18_400
CLOSING_TARGET = 3_000
MAX_SUPPLEMENTS_PER_SECTION = 10


class SpecError(ValueError):
    """Raised when a book spec cannot safely drive manuscript generation."""


def require_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{path} must be an object")
    return value


def require_text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SpecError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def require_int(mapping: dict[str, Any], key: str, path: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SpecError(f"{path}.{key} must be an integer")
    return value


def require_text_list(
    mapping: dict[str, Any], key: str, path: str, minimum: int
) -> list[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or len(value) < minimum:
        raise SpecError(f"{path}.{key} must contain at least {minimum} items")
    result: list[str] = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, str) or not item.strip():
            raise SpecError(f"{path}.{key}[{index}] must be a non-empty string")
        result.append(item.strip())
    return result


def validate_spec(raw: Any) -> dict[str, Any]:
    spec = require_mapping(raw, "spec")
    for key in (
        "slug",
        "title",
        "subtitle",
        "author",
        "theme",
        "promise",
        "differentiation",
    ):
        require_text(spec, key, "spec")
    require_int(spec, "source_rank", "spec")
    slug = spec["slug"].strip()
    if not SLUG_RE.fullmatch(slug):
        raise SpecError("spec.slug must be a lowercase ASCII hyphenated slug")
    require_text_list(spec, "target_reader", "spec", 1)
    require_text_list(spec, "reader_problem", "spec", 2)
    require_text_list(spec, "safety_rules", "spec", 1)

    phase0 = require_mapping(spec.get("phase0"), "spec.phase0")
    for key in (
        "ui",
        "theme_handling",
        "target_reader",
        "book_type",
        "tone",
        "length",
        "image_density",
    ):
        require_text(phase0, key, "spec.phase0")

    intro = require_mapping(spec.get("intro"), "spec.intro")
    require_text(intro, "opening_scene", "spec.intro")
    require_text(intro, "misconception", "spec.intro")
    require_text_list(intro, "reading_guide", "spec.intro", 2)

    closing = require_mapping(spec.get("closing"), "spec.closing")
    for key in ("future_scene", "first_action", "author_message"):
        require_text(closing, key, "spec.closing")

    sources = spec.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SpecError("spec.sources must contain at least one source")
    for index, source_raw in enumerate(sources, 1):
        source = require_mapping(source_raw, f"spec.sources[{index}]")
        for key in ("title", "url", "note"):
            require_text(source, key, f"spec.sources[{index}]")
        if not source["url"].startswith(("https://", "http://")):
            raise SpecError(f"spec.sources[{index}].url must be an HTTP(S) URL")

    chapters = spec.get("chapters")
    if not isinstance(chapters, list) or len(chapters) != 5:
        raise SpecError("spec.chapters must contain exactly five chapters")
    chapter_numbers: list[int] = []
    for chapter_index, chapter_raw in enumerate(chapters, 1):
        path = f"spec.chapters[{chapter_index}]"
        chapter = require_mapping(chapter_raw, path)
        chapter_number = require_int(chapter, "number", path)
        chapter_numbers.append(chapter_number)
        for key in ("title", "goal", "chapter_case"):
            require_text(chapter, key, path)
        sections = chapter.get("sections")
        if not isinstance(sections, list) or len(sections) != 6:
            raise SpecError(f"{path}.sections must contain exactly six sections")
        section_numbers: list[int] = []
        for section_index, section_raw in enumerate(sections, 1):
            section_path = f"{path}.sections[{section_index}]"
            section = require_mapping(section_raw, section_path)
            section_numbers.append(require_int(section, "number", section_path))
            for key in (
                "title",
                "core_message",
                "why_it_matters",
                "scene",
                "reflection",
            ):
                require_text(section, key, section_path)
            require_text_list(section, "explanation_points", section_path, 4)
            require_text_list(section, "action_steps", section_path, 5)
            require_text_list(section, "pitfalls", section_path, 3)
            require_text_list(section, "checklist", section_path, 5)
            case = require_mapping(section.get("case_study"), f"{section_path}.case_study")
            for key in ("profile", "situation", "decision", "outcome"):
                require_text(case, key, f"{section_path}.case_study")
            faqs = section.get("faqs")
            if not isinstance(faqs, list) or len(faqs) < 3:
                raise SpecError(f"{section_path}.faqs must contain at least three items")
            for faq_index, faq_raw in enumerate(faqs, 1):
                faq = require_mapping(faq_raw, f"{section_path}.faqs[{faq_index}]")
                require_text(faq, "question", f"{section_path}.faqs[{faq_index}]")
                require_text(faq, "answer", f"{section_path}.faqs[{faq_index}]")
        if section_numbers != list(range(1, 7)):
            raise SpecError(f"{path}.sections numbers must be 1 through 6")
    if chapter_numbers != list(range(1, 6)):
        raise SpecError("spec.chapters numbers must be 1 through 5")

    image_plan = spec.get("image_plan")
    if not isinstance(image_plan, list) or not image_plan:
        raise SpecError("spec.image_plan must contain at least one planned image")
    filenames: list[str] = []
    for index, image_raw in enumerate(image_plan, 1):
        image = require_mapping(image_raw, f"spec.image_plan[{index}]")
        for key in ("filename", "type", "placement", "purpose", "prompt"):
            require_text(image, key, f"spec.image_plan[{index}]")
        filename = image["filename"]
        if Path(filename).name != filename or not filename.lower().endswith(".png"):
            raise SpecError(f"spec.image_plan[{index}].filename must be a PNG basename")
        filenames.append(filename)
    if len(filenames) != len(set(filenames)):
        raise SpecError("spec.image_plan filenames must be unique")

    kdp = require_mapping(spec.get("kdp"), "spec.kdp")
    require_text_list(kdp, "categories", "spec.kdp", 2)
    require_text_list(kdp, "keywords", "spec.kdp", 7)
    require_text(kdp, "sales_hook", "spec.kdp")
    return spec


def load_spec(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"could not read spec {path}: {exc}") from exc
    return validate_spec(raw)


def punctuate(text: str) -> str:
    text = text.strip()
    if text.endswith(("。", "！", "？", ".", "!", "?")):
        return text
    return text + "。"


def inline_text(text: str) -> str:
    """Return spec prose safe for embedding inside a longer sentence."""
    return text.strip().rstrip("。．.!！?？ ")


def short_reference(text: str, limit: int = 16) -> str:
    """Create a visibly abbreviated pointer without repeating a full spec field."""
    cleaned = inline_text(text)
    if len(cleaned) <= 4:
        return "該当項目…"
    keep = min(limit, len(cleaned) - 1)
    return cleaned[:keep] + "…"


def inline_chapter(chapter: dict[str, Any]) -> dict[str, Any]:
    return {
        **chapter,
        "title": inline_text(chapter["title"]),
        "goal": inline_text(chapter["goal"]),
        "chapter_case": inline_text(chapter["chapter_case"]),
    }


def inline_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        **section,
        "title": inline_text(section["title"]),
        "core_message": inline_text(section["core_message"]),
        "why_it_matters": inline_text(section["why_it_matters"]),
        "scene": inline_text(section["scene"]),
        "reflection": inline_text(section["reflection"]),
        "explanation_points": [
            inline_text(item) for item in section["explanation_points"]
        ],
        "action_steps": [inline_text(item) for item in section["action_steps"]],
        "pitfalls": [inline_text(item) for item in section["pitfalls"]],
        "checklist": [inline_text(item) for item in section["checklist"]],
        "case_study": {
            key: inline_text(value) for key, value in section["case_study"].items()
        },
        "faqs": [
            {
                "question": inline_text(item["question"]),
                "answer": inline_text(item["answer"]),
            }
            for item in section["faqs"]
        ],
    }


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def numbered(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def build_research(spec: dict[str, Any]) -> str:
    source_lines = []
    for source in spec["sources"]:
        source_lines.append(
            f"- [{source['title']}]({source['url']}) — {punctuate(source['note'])}"
        )
    return f"""# テーマリサーチ: {spec['theme']}

## Phase 0回答の要約

- テーマの扱い: {spec['phase0']['theme_handling']}
- 想定読者: {spec['phase0']['target_reader']}
- 本の型: {spec['phase0']['book_type']}
- 文体: {spec['phase0']['tone']}
- 文字量: {spec['phase0']['length']}
- 画像密度: {spec['phase0']['image_density']}
- 回答方法: {spec['phase0']['ui']}

## 読者ニーズ

{bullets(spec['reader_problem'])}

読者が必要としているのは、知識を増やすだけの説明ではありません。自分の場面へ当てはめ、判断し、最初の一歩を選び、迷った時に戻れる手順です。本書は各節に論点、行動手順、落とし穴、架空の複合事例、FAQ、チェックリストを置き、読む行為を実践へ接続します。

## 想定読者

{bullets(spec['target_reader'])}

## 競合・類似コンテンツとの差

{punctuate(spec['differentiation'])}

一般論を広く並べるのではなく、30節それぞれに固有の生活・業務場面と判断材料を割り当てます。著者の実体験を装わず、事例は複数の典型要素を組み合わせた架空の複合事例として明示します。

## 企画への反映方針

- 読者の悩みから始め、背景理解、判断、実行、定着の順で5章を構成する
- 各章6節、全30節を重複のない論点と作業に割り当てる
- 抽象的な励ましだけで終わらせず、手順、失敗時の戻り方、相談境界を示す
- 目標文字数は100,000字、表示文字数の合格範囲は95,000〜105,000字とする

## 注意すべきリスク表現

{bullets(spec['safety_rules'])}

## 参照情報

{chr(10).join(source_lines)}

参照情報は企画と安全境界を支えるために使います。個別事情によって答えが変わる部分は、本文で確認日と相談先を示し、本書だけで最終判断を完結させない構成にします。
"""


def build_project(spec: dict[str, Any]) -> str:
    chapter_lines = "\n".join(
        f"- 第{chapter['number']}章 {chapter['title']}" for chapter in spec["chapters"]
    )
    return f"""# {spec['title']}

## サブタイトル

{spec['subtitle']}

## 著者

{spec['author']}

## テーマ

{spec['theme']}

## ターゲット読者

{bullets(spec['target_reader'])}

## 読者の主な悩み

{bullets(spec['reader_problem'])}

## 本書の約束

{punctuate(spec['promise'])}

## 差別化方針

{punctuate(spec['differentiation'])}

## 章構成

- はじめに
{chapter_lines}
- おわりに

## 文体

{spec['phase0']['tone']}

## 画像方針

{spec['phase0']['image_density']}。本文内容に対応する画像だけを計画し、同じ共通図を節数合わせで使い回しません。画像下の表示キャプションは付けません。画像、表紙、EPUBの生成は次工程で行います。

## 制作条件

- 文字版: complete_text_only
- 目標表示文字数: 100,000字
- 合格範囲: 95,000〜105,000字
- 事例方針: 著者体験を捏造せず、架空の複合事例と明示する
- 公開境界: KDPへの申請・公開は行わない
"""


def build_outline(spec: dict[str, Any]) -> str:
    parts = [f"# 詳細アウトライン: {spec['title']}"]
    parts.extend(
        [
            "",
            "## はじめに",
            "",
            f"- 導入場面: {spec['intro']['opening_scene']}",
            f"- よくある誤解: {spec['intro']['misconception']}",
            f"- 本書の約束: {spec['promise']}",
        ]
    )
    for chapter in spec["chapters"]:
        parts.extend(
            [
                "",
                f"## 第{chapter['number']}章 {chapter['title']}",
                "",
                f"- 章のゴール: {chapter['goal']}",
                f"- 章の複合事例: {chapter['chapter_case']}",
            ]
        )
        for section in chapter["sections"]:
            parts.extend(
                [
                    "",
                    f"### {chapter['number']}-{section['number']} {section['title']}",
                    "",
                    f"- 結論: {section['core_message']}",
                    f"- 重要性: {section['why_it_matters']}",
                    f"- 場面: {section['scene']}",
                    "- 主な論点:",
                    *[f"  - {item}" for item in section["explanation_points"]],
                    "- 実践手順:",
                    *[f"  - {item}" for item in section["action_steps"]],
                    f"- 振り返り: {section['reflection']}",
                ]
            )
    parts.extend(
        [
            "",
            "## おわりに",
            "",
            f"- 未来像: {spec['closing']['future_scene']}",
            f"- 最初の一歩: {spec['closing']['first_action']}",
        ]
    )
    return "\n".join(parts) + "\n"


def intro_base(spec: dict[str, Any]) -> str:
    problems = spec["reader_problem"]
    guides = spec["intro"]["reading_guide"]
    readers = spec["target_reader"]
    safety = spec["safety_rules"]
    sources = spec["sources"]
    return f"""# はじめに

{punctuate(spec['intro']['opening_scene'])} この場面を特別な誰かの話として遠ざける必要はありません。本書が想定するのは、{readers[0]}です。知識が足りないから迷っているのではなく、情報と選択肢が一度に押し寄せ、何から確認すればよいか見えにくくなっているのです。

## 読者の悩みを、作業できる形へ変える

最初の悩みは「{problems[0]}」です。もう一つは「{problems[1]}」です。悩みを一文で言えても、すぐに正解が出るとは限りません。そこで本書では、悩みを観察できる事実、確認すべき情報、自分で決められること、専門家や関係者へ相談することに分けます。分けることで、焦りを小さな作業へ変えられます。

{punctuate(spec['intro']['misconception'])} これは多くの人が入りやすい理解ですが、本書はその誤解を責めません。なぜそう考えやすいのかを確認し、現実的な判断へ戻る道を用意します。強い言葉や万能な方法ではなく、状況ごとに確かめる順序を持つことが、長く使える助けになります。

## 本書が約束すること

{punctuate(spec['promise'])} この約束を、読むだけの標語にはしません。全5章30節に、具体的な場面、理解のポイント、実践手順、落とし穴、架空の複合事例、FAQ、チェックリストを置きます。自分の事情に近い節から読み、必要なページへ戻れる実用書として設計しています。

本書の差別化軸は、{punctuate(spec['differentiation'])} 情報量を競うのではなく、読者が迷いを整理し、次の行動を言葉にできることを優先します。そのため、似た概念を言い換えてページを埋めず、各節には別の判断課題と実践道具を割り当てています。

## 本書の使い方

第一の使い方は、{punctuate(guides[0])} 読みながら気になった箇所へ印を付け、章末ではなく各節のチェックリストで一度止まってください。理解したつもりのまま先へ進むより、今できる一つを選ぶ方が、内容を生活や業務へつなげやすくなります。

第二の使い方は、{punctuate(guides[1])} 一人で決め切れない課題は、家族、同僚、管理者、専門職など、適切な相手と共有します。本書の質問やチェック項目をそのまま会話の準備に使えば、漠然とした相談を具体的な確認へ変えられます。

## 事例と情報源の扱い

本文に登場する事例は、現場で起こり得る複数の要素を組み合わせた架空の複合事例です。実在する個人の経験でも、著者自身の体験談でもありません。状況、判断、結果を分けて示すことで、読者が自分の条件との差を確かめられるようにしています。

本書は「{sources[0]['title']}」を含む公開情報を参照します。参照の目的は、権威の名前で結論を押し付けることではなく、確認できる範囲と個別判断の境界を示すことです。制度や技術、社会状況が変わり得る箇所では、確認日と公式情報への戻り方を意識してください。

## 安全に読むための境界

本書全体で守る第一の原則は「{safety[0]}」です。一般的な情報は、個別事情をすべて含みません。迷いが大きい時、損失や健康、安全、法的責任に関わる時は、本書だけで結論を出さず、公式窓口や資格を持つ専門家へつないでください。

ここから先は、知識を一気に覚える競争ではありません。今の状況を一つ観察し、一つ確認し、一つ行動し、その結果を記録する旅です。完璧に進める必要はありません。途中で止まった時に戻れる場所を持つことも、本書が提供する大切な道具です。
"""


def intro_supplement(spec: dict[str, Any], index: int) -> str:
    readers = spec["target_reader"]
    problems = spec["reader_problem"]
    guides = spec["intro"]["reading_guide"]
    safety = spec["safety_rules"]
    variants = [
        (
            "読み始める前の一枚メモ",
            f"ノートに、いま困っている場面を一つだけ書いてください。対象は「{problems[index % len(problems)]}」です。次に、すでに分かっている事実、まだ推測にすぎないこと、誰かへ確認したいことを三列に分けます。この準備があると、本文の情報を自分へ無理に当てはめず、必要な部分だけを選べます。最後に、今日の読書で決めたいことを一文にし、読み終えた後に答えが変わったかを確認します。",
        ),
        (
            "一人で読む時と一緒に読む時",
            f"{readers[index % len(readers)]}が一人で読む場合は、結論より先にチェック項目へ印を付けます。誰かと一緒に読む場合は、{guides[index % len(guides)]}という使い方を共有し、賛否を決める前に前提条件の違いを探します。同じ言葉でも立場によって見えている範囲は違います。意見が割れた時は、相手を説得するより、どの情報を追加すれば判断できるかを一緒に決めてください。",
        ),
        (
            "途中で不安が強くなった時",
            f"読むほど不安が大きくなった時は、情報を追加し続けないことも選択肢です。「{safety[index % len(safety)]}」という境界に戻り、今すぐ必要な判断か、期限を確認できるか、相談相手がいるかを整理します。緊急性がなければ一度離れ、次に確認する日時だけを決めます。緊急性や大きな損失の可能性があるなら、読書を続けるより公式窓口や専門家への連絡を優先します。",
        ),
        (
            "本書に書かれていないこと",
            f"本書は「{spec['theme']}」について、すべての人へ同じ答えを出すものではありません。{problems[(index + 1) % len(problems)]}という悩みの背景には、家庭、職場、地域、契約、健康など本文だけでは分からない条件があります。書かれていない条件を無視して例へ自分を合わせず、違いを見つけたら余白へ記録してください。その違いこそ、個別相談で最初に伝えるべき材料になります。",
        ),
        (
            "情報源へ戻る道",
            f"本文の説明に迷ったら、結論だけを検索し直すのではなく、参照元の「{spec['sources'][index % len(spec['sources'])]['title']}」へ戻ります。発信日、対象、前提、例外を確認し、自分が必要とする答えと資料が答えている範囲を比べてください。資料にないことは推測で埋めず、未確認としてノートへ残します。更新があるテーマでは、判断日と確認日も一緒に書きます。",
        ),
        (
            "ノートの共通書式",
            f"各節の記録は、日付、場面、確認できた事実、次の行動、相談先の五項目にそろえます。題材は「{problems[index % len(problems)]}」です。書式を固定すると、後から章をまたいで振り返る時にも変化を追えます。感想を書くことも大切ですが、感想と確認事実は欄を分けてください。次回の自分や別の担当者が読んでも現在地が分かる記録を目指します。",
        ),
        (
            "読み飛ばしてよい場所",
            f"すべての節を同じ濃さで読む必要はありません。{readers[index % len(readers)]}に直接関係する場面、期限が近い場面、損失や安全への影響が大きい場面を先に選びます。関係の薄い節は見出しとチェックリストだけ確認し、必要になった時の戻り先として印を付けます。通読の達成感より、いま必要な判断に時間を使うことを優先してください。",
        ),
        (
            "中断を選ぶ基準",
            f"本文を読んで新しい行動を始める前に、停止条件も決めます。情報の出所が確認できない、影響範囲が読めない、関係者の同意がない、「{safety[index % len(safety)]}」に触れる、のいずれかなら一度止めます。止まることは先延ばしではありません。何を確認すれば再開できるかを一文にし、確認先と期限を決める安全な判断です。",
        ),
        (
            "行動と結果を分ける",
            f"本書で評価するのは、望んだ結果が出たかだけではありません。「{guides[index % len(guides)]}」を実行できたか、決めた手順を確認できたかも記録します。結果は外部条件に左右されますが、行動手順は改善できます。結果が出なかった時も、観察、相談、記録のどこまでできたかを見れば、次に変える一点を選びやすくなります。",
        ),
        (
            "最初の章を選ぶ",
            f"最初から第1章へ進む以外に、いまの悩みに近い章から読む方法もあります。「{problems[(index + 1) % len(problems)]}」が切迫しているなら、目次で同じ場面を探してください。選んだ章を読んだ後、第1章へ戻って前提を確認します。実践と基礎を往復することで、抽象的な説明を自分の場面に結び付けられます。",
        ),
    ]
    title, body = variants[index % len(variants)]
    return f"## {title} {index + 1}\n\n{body}\n"


def section_base(
    spec: dict[str, Any], chapter: dict[str, Any], section: dict[str, Any]
) -> str:
    chapter = inline_chapter(chapter)
    section = inline_section(section)
    cnum = chapter["number"]
    snum = section["number"]
    points = section["explanation_points"][:4]
    actions = section["action_steps"][:5]
    pitfalls = section["pitfalls"][:3]
    faqs = section["faqs"][:3]
    checklist = section["checklist"][:5]
    case = section["case_study"]
    parts = [
        f"### {cnum}-{snum} {section['title']}",
        "",
        punctuate(section["scene"])
        + f" 「{section['title']}」で最初に守る結論は、{punctuate(section['core_message'])}"
        + f" なぜこの順序が必要かというと、{punctuate(section['why_it_matters'])}",
        "",
        "#### この節の結論",
        "",
        f"本節の判断軸は「{section['core_message']}」です。"
        + f" 読者は「{section['scene']}」という場面について、観察事実、決定者、期限、相談先を分けます。"
        + f" 「{section['why_it_matters']}」という理由を、次の四論点と五手順で実務へ落とします。",
        "",
        "#### 理解しておきたい四つのポイント",
        "",
    ]
    transitions = [
        "最初のポイント",
        "次に確認するポイント",
        "判断が分かれやすいポイント",
        "実行前に押さえるポイント",
    ]
    for index, point in enumerate(points):
        related_action = actions[index % len(actions)]
        related_pitfall = pitfalls[index % len(pitfalls)]
        evidence = checklist[index % len(checklist)]
        parts.extend(
            [
                f"##### {index + 1}. {point}",
                "",
                f"{transitions[index]}は「{point}」です。"
                + f" 場面「{section['scene']}」から関係する事実を選び、「{related_action}」へつなげます。"
                + f" 「{evidence}」を判断の証拠とし、「{related_pitfall}」が見えたら前提確認へ戻ります。",
                "",
            ]
        )
    parts.extend(["#### 五つの実践手順", ""])
    artifact_types = ["確認メモ", "照会記録", "依頼文", "試行記録", "見直し表"]
    for index, action in enumerate(actions, 1):
        check = checklist[(index - 1) % len(checklist)]
        stop = pitfalls[(index - 1) % len(pitfalls)]
        recovery = actions[max(0, index - 2)]
        confirmation = faqs[(index - 1) % len(faqs)]["answer"]
        artifact = artifact_types[(index - 1) % len(artifact_types)]
        parts.extend(
            [
                f"{index}. **{action}**",
                "",
                f"手順{index}「{action}」の成果物は、「{check}」と記した{artifact}です。"
                + f" 「{stop}」で停止し、「{confirmation}」を確認できなければ「{recovery}」へ戻って再開日を決めます。",
                "",
            ]
        )
    parts.extend(["#### 起こりやすい落とし穴", ""])
    for index, pitfall in enumerate(pitfalls, 1):
        recovery = actions[min(index, len(actions) - 1)]
        check = checklist[(index + 1) % len(checklist)]
        confirmation = faqs[(index - 1) % len(faqs)]["answer"]
        parts.extend(
            [
                f"##### 落とし穴{index}: {pitfall}",
                "",
                f"「{pitfall}」の目印は、「{check}」を説明できない状態です。"
                + f" 「{recovery}」へ戻って「{confirmation}」を確認し、修正理由を同じ場面の停止条件として残します。",
                "",
            ]
        )
    parts.extend(
        [
            "#### 独立した架空の複合事例",
            "",
            f"第{cnum}章の通し事例「{chapter['chapter_case']}」とは別に、「{section['title']}」の条件差を示す独立した架空の複合事例として、{punctuate(case['profile'])} 実在人物や著者の経験ではありません。",
            "",
            f"状況は{punctuate(case['situation'])} 「{section['core_message']}」を軸に、確認済み事実と未確認事項を分けます。",
            "",
            f"判断と行動は{punctuate(case['decision'])} 「{checklist[0]}」を成果物とし、「{pitfalls[0]}」を停止条件にしました。",
            "",
            f"結果は{punctuate(case['outcome'])} 読者は「{section['reflection']}」と問い、条件差を記録します。",
            "",
            "#### よくある質問",
            "",
        ]
    )
    for index, faq in enumerate(faqs, 1):
        next_action = actions[index % len(actions)]
        evidence = checklist[index % len(checklist)]
        parts.extend(
            [
                f"##### Q{index}. {faq['question']}",
                "",
                f"**A.** {punctuate(faq['answer'])} 次に「{next_action}」を行い、「{evidence}」と記録できなければ回答先へ条件を問い直します。",
                "",
            ]
        )
    parts.extend(
        [
            "#### 実践チェックリスト",
            "",
            *[f"- [ ] {item}" for item in checklist],
            "",
            f"「{section['title']}」の未完了項目には、確認先、担当、期限を一つずつ書きます。最初に補うのは「{checklist[0]}」へ最も影響する項目です。",
            "",
            "#### 振り返りの問い",
            "",
            punctuate(section["reflection"])
            + f" 「{section['core_message']}」という判断軸を使う前後で答えを比較し、変化を生んだ情報と次回確認日を記します。",
            "",
        ]
    )
    return "\n".join(parts)


def section_supplement(
    spec: dict[str, Any],
    chapter: dict[str, Any],
    section: dict[str, Any],
    index: int,
) -> str:
    chapter = inline_chapter(chapter)
    section = inline_section(section)
    points = section["explanation_points"]
    actions = section["action_steps"]
    pitfalls = section["pitfalls"]
    checklist = section["checklist"]
    faqs = section["faqs"]
    case = section["case_study"]
    readers = spec["target_reader"]
    variants: list[tuple[str, str]] = [
        (
            "確認票",
            f"「{section['title']}」用の確認票は四欄です。第一欄には場面「{section['scene']}」から確認できた日時と言葉、第二欄には未確認の「{points[0]}」、第三欄には担当する「{actions[0]}」、第四欄には完了条件「{checklist[0]}」を書きます。「{pitfalls[0]}」が起きた場合は第四欄を完了にせず、確認相手と再開日を追記します。この一枚が次の担当者へ渡せる成果物です。",
        ),
        (
            "会話例",
            f"「{section['title']}」を相談する冒頭は、『いま{section['scene']}という状況です。私は{points[1]}を確認したいです。{faqs[0]['question']}』です。相手から「{faqs[0]['answer']}」という回答を得たら、『では、{actions[1]}をいつまでに行い、{checklist[1]}をどこへ記録すればよいですか』と問い直します。「{pitfalls[1]}」を避けるため、会話の最後に担当者名と次の連絡日を復唱します。",
        ),
        (
            "役割表",
            f"「{section['title']}」の役割表には、本人、家族・同僚、窓口・専門職の三行を作ります。本人が決める材料は「{points[2]}」、家族や同僚が担う作業は「{actions[2]}」、窓口へ確認する質問は「{faqs[1]['question']}」です。各行へ主担当、代理、期限を一つずつ置き、「{checklist[2]}」を確認できた人が更新します。「{pitfalls[2]}」が起きたら、主担当ではなく代理が確認を引き継ぎます。",
        ),
        (
            "境界事例",
            f"「{section['title']}」の境界を二つの選択で比べます。選択Aは「{actions[3]}」を確認せず進めるため、「{pitfalls[0]}」が起きても戻れません。選択Bは「{faqs[2]['answer']}」という条件を確認し、「{checklist[3]}」を成果物にします。Aを選びそうになった時の停止文は『まだ{points[3]}を確認していないので、今日は決定せず{actions[3]}へ戻ります』です。",
        ),
        (
            "三段階の予定表",
            f"「{section['title']}」の予定表では、今日を「{actions[0]}」、期限内を「{actions[2]}」、見直し日を「{actions[4]}」に割り当てます。今日の完了証拠は「{checklist[0]}」、期限内の完了証拠は「{checklist[2]}」、見直し日の確認質問は「{section['reflection']}」です。「{pitfalls[1]}」が見えた場合だけ予定を止め、誰へ確認していつ再開するかを余白へ書きます。",
        ),
        (
            "記録台帳",
            f"「{section['title']}」の台帳は、日付、判断材料、実行者、費用・時間、結果、次回確認の六列です。「{case['decision']}」を記入例にすると、判断材料は「{points[2]}」、実行欄は「{actions[2]}」、結果欄は「{case['outcome']}」になります。「{pitfalls[1]}」が生じた選択肢も削除せず、採用しなかった理由と「{checklist[4]}」の確認日を残します。",
        ),
        (
            "引継ぎメモ",
            f"{readers[index % len(readers)]}が「{section['title']}」を引き継ぐ時は、現状を「{case['situation']}」、実施済みを「{case['decision']}」、未完了を「{actions[4]}」と書き分けます。次の担当者へは「{faqs[1]['question']}」を確認してもらい、「{checklist[4]}」を更新条件にします。「{pitfalls[2]}」の兆候があれば、前担当へ戻すのではなく確認先と代理担当を決めます。",
        ),
        (
            "例外時の戻り方",
            f"「{section['title']}」で時間が半分しかない例外時は、「{actions[0]}」と「{checklist[0]}」だけを先に確保します。協力者が不在なら「{actions[3]}」を保留し、「{faqs[2]['answer']}」で確認先を探します。反対に協力者が増えた場合は「{actions[4]}」を代理へ渡し、「{pitfalls[2]}」が起きないよう更新責任を明記します。通常手順へ戻る日は「{section['reflection']}」への回答で決めます。",
        ),
        (
            "比較表",
            f"「{section['title']}」の比較表では、案A「{actions[0]}」と案B「{actions[4]}」を、本人への影響、家族・職場の負担、取り消しやすさ、確認先の四列で比べます。案Aの注意点は「{pitfalls[0]}」、案Bの注意点は「{pitfalls[2]}」です。採用条件を「{checklist[4]}」と定め、条件を満たさない場合は「{faqs[0]['answer']}」へ戻って情報を補います。",
        ),
        (
            "レビュー票",
            f"「{section['title']}」のレビュー日には、「{section['reflection']}」へ再回答します。前回から変わった事実は「{points[0]}」、続ける作業は「{actions[3]}」、終了できる条件は「{checklist[3]}」です。「{pitfalls[2]}」が再発した場合は同じ行動を繰り返さず、「{faqs[2]['answer']}」という確認を行って担当と期限を更新します。",
        ),
    ]
    if index >= len(variants):
        raise SpecError(
            f"section {chapter['number']}-{section['number']} needs excessive padding"
        )
    title, body = variants[index]
    return f"#### 実践補助 {index + 1}: {title}\n\n{body}\n"


def section_base_compact(
    spec: dict[str, Any], chapter: dict[str, Any], section: dict[str, Any]
) -> str:
    """Render every rich-spec field once, without prose-multiplier reuse."""
    del spec
    chapter = inline_chapter(chapter)
    section = inline_section(section)
    cnum = chapter["number"]
    snum = section["number"]
    ref = f"{cnum}-{snum}"
    parts = [
        f"### {ref} {section['title']}",
        "",
        f"#### 節{ref}の出発点",
        "",
        punctuate(section["scene"]),
        "",
        f"節{ref}では、ここに書かれた場面を観察事実と未確認事項へ分け、次の判断軸へ進みます。",
        "",
        "#### 判断軸",
        "",
        punctuate(section["core_message"]),
        "",
        punctuate(section["why_it_matters"]),
        "",
        f"節{ref}の二つの文章は、結論と理由を分けて記録するための土台です。",
        "",
        "#### 確認する論点",
        "",
    ]
    parts.extend(
        f"{index}. {point}"
        for index, point in enumerate(section["explanation_points"], 1)
    )
    parts.extend(
        [
            "",
            f"節{ref}では、論点番号ごとに確認先と確認日を余白へ書き、未確認の論点を事実扱いしません。",
            "",
            "#### 実践手順",
            "",
        ]
    )
    parts.extend(
        f"{index}. {action}"
        for index, action in enumerate(section["action_steps"], 1)
    )
    parts.extend(
        [
            "",
            f"節{ref}の手順には、主担当、期限、完了の証拠を一つずつ割り当てます。順序を変える場合は理由も記録します。",
            "",
            "#### 停止条件と落とし穴",
            "",
        ]
    )
    parts.extend(
        f"{index}. {pitfall}" for index, pitfall in enumerate(section["pitfalls"], 1)
    )
    parts.extend(
        [
            "",
            f"節{ref}で停止条件に当たったら、次の手順を増やさず、該当番号と確認相手だけを記録します。",
            "",
            "#### 独立した架空の複合事例",
            "",
            f"節{ref}の事例は、第{cnum}章の通し事例とは別条件を示す独立した架空の複合事例です。実在人物や著者の経験ではありません。",
            "",
            f"- 登場人物: {section['case_study']['profile']}",
            f"- 状況: {section['case_study']['situation']}",
            f"- 判断と行動: {section['case_study']['decision']}",
            f"- 結果と学び: {section['case_study']['outcome']}",
            "",
            f"節{ref}の事例は結果をまねるためでなく、自分との条件差を見つける比較材料として使います。",
            "",
            "#### よくある質問",
            "",
        ]
    )
    for index, faq in enumerate(section["faqs"], 1):
        parts.extend(
            [
                f"##### Q{index}. {faq['question']}",
                "",
                f"**A.** {punctuate(faq['answer'])}",
                "",
            ]
        )
    parts.extend(
        [
            f"節{ref}のFAQで条件が足りない場合は、回答を広げて推測せず、質問番号と不足条件を相談先へ伝えます。",
            "",
            "#### 実践チェックリスト",
            "",
            *[f"- [ ] {item}" for item in section["checklist"]],
            "",
            f"節{ref}のチェックは、完了日と確認者を添えて初めて引継ぎ可能な記録になります。",
            "",
            "#### 振り返りの問い",
            "",
            punctuate(section["reflection"]),
            "",
            f"節{ref}の答えには、現在の判断、根拠、次回確認日の三点を残します。",
            "",
        ]
    )
    return "\n".join(parts)


def section_supplement_compact(
    spec: dict[str, Any],
    chapter: dict[str, Any],
    section: dict[str, Any],
    index: int,
) -> str:
    """Add one section-specific work artifact using only abbreviated field refs."""
    del spec
    chapter = inline_chapter(chapter)
    section = inline_section(section)
    ref = f"{chapter['number']}-{section['number']}"
    points = [short_reference(item) for item in section["explanation_points"]]
    actions = [short_reference(item) for item in section["action_steps"]]
    pitfalls = [short_reference(item) for item in section["pitfalls"]]
    checks = [short_reference(item) for item in section["checklist"]]
    questions = [short_reference(item["question"]) for item in section["faqs"]]
    profile = short_reference(section["case_study"]["profile"])
    variants: list[tuple[str, str]] = [
        (
            "確認票",
            f"節{ref}の確認票は、観察事実、未確認、担当、期限、証拠の五欄です。観察事実には節冒頭の場面を一文で転記せず要約し、未確認欄へ論点1「{points[0]}」の番号を書きます。担当欄は手順1「{actions[0]}」、証拠欄は確認項目1「{checks[0]}」へ対応させます。停止条件1「{pitfalls[0]}」に触れた場合は完了印を付けず、確認相手と再開日を追記します。節{ref}の確認票は、一枚で現在地を説明できることを完成条件にします。",
        ),
        (
            "会話例",
            f"節{ref}の相談は、『現在地を一文で説明します。論点2「{points[1]}」を確認したく、質問1「{questions[0]}」について教えてください』と始めます。回答後は、『手順2「{actions[1]}」の担当と期限、確認項目2「{checks[1]}」の残し方を確認します』と復唱します。節{ref}で停止条件2「{pitfalls[1]}」が見えた時は結論を迫らず、分からない条件だけを質問へ戻します。会話の終了時刻、相手の所属、次の連絡日を記録すれば、口頭相談を引き継げます。",
        ),
        (
            "役割表",
            f"節{ref}の役割表は、本人、家族・同僚、窓口・専門職の三行で作ります。本人の判断欄へ論点3「{points[2]}」、支援する側の作業欄へ手順3「{actions[2]}」、外部確認欄へ質問2「{questions[1]}」を番号で配置します。主担当が動けない時の代理も決め、確認項目3「{checks[2]}」を更新できる人を一人に絞ります。節{ref}の事例人物「{profile}」と自分の役割差を一行で残し、愛情の量ではなく時間・距離・権限で分担します。",
        ),
        (
            "境界事例",
            f"節{ref}では、進める場合と止める場合を二列で比べます。進める列は論点4「{points[3]}」を確認し、手順4「{actions[3]}」を実行して確認項目4「{checks[3]}」が残る状態です。止める列は停止条件1「{pitfalls[0]}」があり、質問3「{questions[2]}」への回答も得られていない状態です。節{ref}の境界文は『条件が一つ未確認なので今日は決定せず、確認先と期限だけ決めます』とします。止めた理由を記録すれば、保留と放置を区別できます。",
        ),
        (
            "時間割",
            f"節{ref}の時間割は、今日、期限内、見直し日の三段です。今日の欄へ手順1「{actions[0]}」、期限内へ手順3「{actions[2]}」、見直し日へ手順5「{actions[4]}」を番号で置きます。今日の証拠は確認項目1「{checks[0]}」、期限内の証拠は確認項目3「{checks[2]}」です。節{ref}で停止条件2「{pitfalls[1]}」が起きた時だけ時計を止め、確認相手の返答予定日を新しい再開日にします。すべてを同じ緊急度にしないことが時間割の目的です。",
        ),
        (
            "記録台帳",
            f"節{ref}の台帳には、日付、選択肢、決定者、費用・時間、根拠、結果の六列を置きます。選択肢欄へ手順2「{actions[1]}」と手順4「{actions[3]}」の番号を並べ、根拠欄へ論点2「{points[1]}」を書きます。結果欄は確認項目5「{checks[4]}」の達否で記録し、停止条件3「{pitfalls[2]}」が出た選択肢も消しません。節{ref}の台帳では採用しなかった理由を残すことで、後から家族・職場・窓口へ判断経緯を説明できます。",
        ),
        (
            "引継ぎメモ",
            f"節{ref}の引継ぎメモは、現状、実施済み、保留、次の担当、期限の五行です。現状は節冒頭の場面を短く要約し、実施済みへ手順1「{actions[0]}」、保留へ質問2「{questions[1]}」、期限へ確認項目4「{checks[3]}」の確認日を書きます。節{ref}で停止条件3「{pitfalls[2]}」が続く場合は、前担当へ丸投げせず代理担当と外部確認先を指定します。読み手が追加質問なしで最初の一手を選べれば、引継ぎメモは完成です。",
        ),
        (
            "例外時の復帰表",
            f"節{ref}で時間が半分しかない時は、手順1「{actions[0]}」と確認項目1「{checks[0]}」だけを先に確保します。担当者が不在なら手順4「{actions[3]}」を保留し、質問3「{questions[2]}」の確認先を探します。協力者が増えた場合は手順5「{actions[4]}」を代理へ渡しますが、停止条件3「{pitfalls[2]}」の監視者も決めます。節{ref}の通常手順へ戻る日は、振り返り欄へ現在の根拠と再開条件を書けた時点です。例外対応を恒久運用へ変えないことも確認します。",
        ),
        (
            "比較表",
            f"節{ref}の比較表は、案Aを手順1「{actions[0]}」、案Bを手順5「{actions[4]}」として、本人への影響、周囲の負担、取り消しやすさ、確認先の四列で比べます。案Aの注意は停止条件1「{pitfalls[0]}」、案Bの注意は停止条件3「{pitfalls[2]}」です。採用条件を確認項目5「{checks[4]}」とし、満たさない場合は質問1「{questions[0]}」へ戻ります。節{ref}では点数だけで決めず、譲れない条件を一つ先に選んで比較理由を残します。",
        ),
        (
            "レビュー票",
            f"節{ref}のレビュー票には、変わった事実、続ける手順、止める手順、新しい確認先、次回日を記入します。変わった事実は論点1「{points[0]}」の観察から選び、続ける候補を手順4「{actions[3]}」、完了条件を確認項目4「{checks[3]}」へ対応させます。停止条件3「{pitfalls[2]}」が再発した場合は同じ手順を繰り返さず、質問3「{questions[2]}」を使って条件を更新します。節{ref}の振り返り回答が前回と変わった理由も一行残せば、レビューを惰性から切り離せます。",
        ),
    ]
    if index >= len(variants):
        raise SpecError(
            f"section {chapter['number']}-{section['number']} needs excessive compact expansion"
        )
    title, body = variants[index]
    return f"#### 節{ref}の実践ワーク {index + 1}: {title}\n\n{body}\n"


def chapter_preamble(chapter: dict[str, Any]) -> str:
    chapter = inline_chapter(chapter)
    return f"""# 第{chapter['number']}章 {chapter['title']}

第{chapter['number']}章のゴールは、{punctuate(chapter['goal'])} 章の通し事例は、{punctuate(chapter['chapter_case'])} この第{chapter['number']}章の通し事例が「{chapter['title']}」の時間経過を示します。一方、第{chapter['number']}章の各節には条件差を比較する独立した架空の複合事例を置き、実在人物や著者体験とは明確に区別します。

第{chapter['number']}章を最初からすべて理解する必要はありません。「{chapter['title']}」を考える各節は、場面、結論、論点、手順、落とし穴、事例、FAQ、チェックリストの順で進みます。第{chapter['number']}章で自分に近い場面では立ち止まり、違う場面では条件差を確認してください。章末では「{chapter['goal']}」ための次の作業を一文にします。
"""


def render_chapter(
    chapter: dict[str, Any], section_records: list[dict[str, Any]]
) -> str:
    chapter = inline_chapter(chapter)
    chunks = [chapter_preamble(chapter)]
    for record in section_records:
        chunks.append(record["base"])
        chunks.extend(record["extras"])
    chunks.append(
        f"## 第{chapter['number']}章のまとめ\n\n"
        f"第{chapter['number']}章では「{chapter['goal']}」を六つの場面で確認しました。"
        + f" 「{chapter['title']}」について暗記するのではなく、確認先、成果物、停止条件、復帰手順を言葉にできることが到達点です。"
        + f" 章の通し事例「{chapter['chapter_case']}」と独立事例の条件差を比べ、未完了項目を一つ選んで次章へ引き継いでください。\n"
    )
    return "\n\n".join(chunks).rstrip() + "\n"


def closing_base(spec: dict[str, Any]) -> str:
    closing = spec["closing"]
    first_chapter = spec["chapters"][0]
    last_chapter = spec["chapters"][-1]
    return f"""# おわりに

{punctuate(closing['future_scene'])} その未来は、すべての問題が消えた姿ではありません。迷った時に確認する順序が分かり、相談相手へ状況を説明でき、失敗しても戻る位置を持っている状態です。本書が目指したのは、強い自信ではなく、現実の中で動き直せる足場でした。

## 五つの章を振り返る

第1章では「{first_chapter['goal']}」ことから始めました。その後、背景を理解し、判断材料を分け、実践手順を組み、最後の第5章では「{last_chapter['goal']}」ところまで進みました。どの章にも共通していたのは、事実と解釈を分けること、個別条件を確認すること、小さく実行すること、結果を記録することです。

読後に未完了のチェック項目が残っていても問題ありません。むしろ、何が終わっていないか見えることは前進です。終えていない項目を一つ選び、情報不足、時間不足、権限不足、相談相手不足のどれに近いかを書いてください。原因が分かれば、次の行動を必要以上に大きくせずに済みます。

## 24時間以内の一歩

{punctuate(closing['first_action'])} この一歩を実行する時、完璧な準備を待たないでください。十五分でできる範囲に切り分け、終わった証拠を一つ残します。メモ、予約、確認メール、家族との会話予定など、形はテーマに合わせて選べます。

実行できなかった場合も失敗とは決めません。何が邪魔をしたかを記録し、行動を半分の大きさにします。明日もう一度試すのか、誰かへ相談するのか、期限を置き直すのかを選びます。行動を責任感の問題にせず、条件を調整する作業として扱ってください。

## 一週間後の確認

一週間後には、実行回数だけでなく判断のしやすさを振り返ります。以前より事実と推測を分けられたか、相談時に状況を説明できたか、戻る手順が使えたかを確認します。成果が見えにくい時は、変化がなかったのか、観察方法がなかったのかを分けて考えます。

また、本文の情報が今も有効かを確かめる習慣も持ってください。制度、技術、サービス、社会状況は変わります。本書に書かれた日付や条件を固定された真理として扱わず、重要な判断の前には公式情報へ戻ります。

## 事例を自分の人生に置き換えすぎない

本書の事例はすべて架空の複合事例です。登場人物がうまく進んだ場面も、そのまま同じ行動をすれば同じ結果になるという約束ではありません。自分と事例の違いを三つ探し、その違いが判断へどう影響するかを考えてください。

一方で、違いがあるから何も使えないわけでもありません。結論ではなく、質問の作り方、確認の順序、役割分担、記録方法を持ち帰れます。状況が変わっても使えるのは、答えより判断の道具です。

## 最後に

{punctuate(closing['author_message'])} 読み終えた今、最初に抱えていた悩みへ同じ言葉で答える必要はありません。答えが少し具体的になり、次に確かめることが見えていれば十分です。

大きな変化は、小さな確認を積み重ねた後に振り返って初めて見えることがあります。今日の一歩を小さく記録し、迷ったら必要な節へ戻ってください。本書が、急いで正解を選ぶためではなく、自分と周囲を守りながら前へ進むための作業台になることを願っています。
"""


def closing_sources(spec: dict[str, Any]) -> str:
    information_checked_at = datetime.now().astimezone().date().isoformat()
    source_lines = "\n".join(
        f"- [{source['title']}]({source['url']}) — {source['note']}"
        for source in spec["sources"]
    )
    return f"""## 出典・確認先

- 情報確認日: {information_checked_at}
- 制度、相談窓口、サービス条件は変わるため、重要な判断の直前にリンク先の最新版を確認してください。

{source_lines}
"""


def closing_supplement(spec: dict[str, Any], index: int) -> str:
    actions = [chapter["sections"][0]["action_steps"][0] for chapter in spec["chapters"]]
    safety = spec["safety_rules"]
    variants = [
        (
            "30日後の棚卸し",
            f"30日後には、できたことを数えるだけでなく、判断の質を確認します。「{actions[index % len(actions)]}」を行った時、前提を記録できたか、途中で相談できたか、結果を見て修正できたかを振り返ります。続ける行動、やめる行動、条件を変えて試す行動を一つずつ選びます。何となく継続するのではなく、理由を言葉にして次の30日へつなげてください。",
        ),
        (
            "誰かへ手渡す時",
            f"本書の内容を家族や同僚へ共有する時は、全部を読ませようとしないでください。相手に関係する場面を一つ選び、現在の事実、困っていること、確認したいことを短く伝えます。「{spec['promise']}」という本書の約束も、相手の事情に合わせて小さな目的へ置き換えます。共有後は、誰が正しいかではなく、次に誰が何を確認するかを決めます。",
        ),
        (
            "安全境界の再確認",
            f"最後に「{safety[index % len(safety)]}」という原則をもう一度確認します。知識が増えると、自分で判断できる範囲まで広がったように感じることがあります。しかし、影響が大きい判断ほど、一般情報と個別相談の境界が重要です。迷った時は判断を急ぐのではなく、公式情報、契約条件、専門職など適切な確認先を選ぶこと自体を行動として評価してください。",
        ),
        (
            "再開の合図",
            f"しばらく実践できない時期があっても、最初から読み直す必要はありません。最後に記録した事実を読み、いまも同じ条件かを確認します。次に「{actions[(index + 1) % len(actions)]}」を十五分だけ行います。再開日と次回確認日を決めれば、空白期間を失敗として埋め合わせず、現在地から無理なく戻れます。",
        ),
        (
            "三か月後の更新",
            f"三か月後には、最初に使った情報源、相談先、期限が今も有効かを確認します。「{actions[index % len(actions)]}」の結果だけでなく、前提条件が変わっていないかも見直してください。変化がなければ確認日を更新し、変化があれば影響する章へ印を付けます。古い判断を責めるのではなく、その時点の情報で何を決めたかを残すことが次の判断を助けます。",
        ),
        (
            "条件が変わった時",
            f"仕事、家族、地域、制度などの条件が変わったら、以前の計画を守ることより再評価を優先します。まず変わった事実を一つ書き、「{actions[(index + 2) % len(actions)]}」が今も必要か確認します。続ける、修正する、止めるの三択を並べ、理由と次回確認日を添えます。計画変更を失敗と見なさず、現実へ合わせる管理作業として扱ってください。",
        ),
        (
            "古いメモの整理",
            f"記録が増えたら、現行、保留、終了の三つに分けます。現行には次の行動があるもの、保留には確認待ちのもの、終了には結果と学びを書いたものを置きます。「{safety[index % len(safety)]}」に関係する資料は、自己判断で要約だけを残さず、公式情報へのリンクと確認日も保存します。整理により、古い条件を現在の判断へ混ぜる事故を防げます。",
        ),
        (
            "小さな前進を数える",
            f"前進は大きな成果だけではありません。質問を一つ言語化した、確認先を見つけた、相談日を決めた、誤った前提に気づいたことも数えます。「{actions[(index + 3) % len(actions)]}」に至らなくても、その前の準備ができていれば記録してください。小さな前進を見える化すると、焦りから不要な近道を選ぶのを避けやすくなります。",
        ),
        (
            "次に読む人への申し送り",
            f"家族や同僚が後から本書を使う場合に備え、現在の状況、確認済みの情報、未確認事項、次の期限を一枚へまとめます。結論だけを渡すと前提が抜けるため、「{spec['promise']}」という目的も短く添えます。相手には同じ結論を求めず、条件差へ印を付けてもらいます。その違いが、次の会話で確認すべき論点になります。",
        ),
        (
            "自分への最後の質問",
            f"本を閉じる前に、「いま最も影響が大きく、まだ確認できていないことは何か」と自分へ問いかけます。答えが出たら、それを調べるのか、相談するのか、期限まで保留するのかを選びます。「{actions[(index + 4) % len(actions)]}」を使えるなら予定へ入れ、使えないなら不足条件を書きます。問いを行動へ変えたところで、この読書はいったん完了です。",
        ),
    ]
    title, body = variants[index % len(variants)]
    return f"## {title} {index + 1}\n\n{body}\n"


def pad_document(
    base: str,
    target: int,
    factory: Callable[[int], str],
    maximum_additions: int = 16,
) -> str:
    chunks = [base.rstrip()]
    index = 0
    while len(visible_text("\n\n".join(chunks))) < target:
        if index >= maximum_additions:
            raise SpecError("could not reach document target without excessive padding")
        chunks.append(factory(index).rstrip())
        index += 1
    return "\n\n".join(chunks).rstrip() + "\n"


def build_manuscripts(
    spec: dict[str, Any], target_total: int, maximum: int
) -> dict[str, str]:
    manuscripts: dict[str, str] = {}
    manuscripts["00_はじめに.md"] = pad_document(
        intro_base(spec), INTRO_TARGET, lambda index: intro_supplement(spec, index)
    )

    chapter_records: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for chapter in spec["chapters"]:
        records = [
            {
                "section": section,
                "base": section_base(spec, chapter, section),
                "extras": [],
            }
            for section in chapter["sections"]
        ]
        cursor = 0
        rendered = render_chapter(chapter, records)
        while len(visible_text(rendered)) < CHAPTER_TARGET:
            record = records[cursor % len(records)]
            extra_index = len(record["extras"])
            if extra_index >= MAX_SUPPLEMENTS_PER_SECTION:
                raise SpecError(f"chapter {chapter['number']} requires excessive expansion")
            record["extras"].append(
                section_supplement(spec, chapter, record["section"], extra_index)
            )
            cursor += 1
            rendered = render_chapter(chapter, records)
        chapter_records.append((chapter, records))
        manuscripts[f"0{chapter['number']}_第{chapter['number']}章.md"] = rendered

    source_appendix = closing_sources(spec)
    closing_body_target = max(
        1_200, CLOSING_TARGET - len(visible_text(source_appendix))
    )
    closing = pad_document(
        closing_base(spec),
        closing_body_target,
        lambda index: closing_supplement(spec, index),
    )
    manuscripts["06_おわりに.md"] = (
        closing.rstrip() + "\n\n" + source_appendix.rstrip() + "\n"
    )

    def total_count() -> int:
        return sum(len(visible_text(text)) for text in manuscripts.values())

    expansion_cursor = 0
    while total_count() < target_total:
        chapter, records = chapter_records[expansion_cursor % len(chapter_records)]
        section_index = (expansion_cursor // len(chapter_records)) % len(records)
        record = records[section_index]
        extra_index = len(record["extras"])
        if extra_index >= MAX_SUPPLEMENTS_PER_SECTION:
            raise SpecError("could not reach total target without excessive section expansion")
        record["extras"].append(
            section_supplement(spec, chapter, record["section"], extra_index)
        )
        manuscripts[f"0{chapter['number']}_第{chapter['number']}章.md"] = render_chapter(
            chapter, records
        )
        expansion_cursor += 1

    total = total_count()
    if total > maximum:
        raise SpecError(
            f"generated visible text is {total:,} characters, above maximum {maximum:,}"
        )
    return manuscripts


def paragraph_duplicates(manuscripts: dict[str, str]) -> list[str]:
    paragraphs: list[str] = []
    for markdown in manuscripts.values():
        for block in re.split(r"\n\s*\n", markdown):
            normalized = re.sub(r"\s+", "", block)
            normalized = re.sub(r"^(?:#{1,6}|[-+*]|\d+[.)])", "", normalized)
            normalized = normalized.replace("*", "").replace("`", "")
            if len(normalized) >= 80:
                paragraphs.append(normalized)
    return sorted(text for text, count in Counter(paragraphs).items() if count > 1)


def build_image_plan(spec: dict[str, Any]) -> str:
    parts = [
        f"# 画像計画: {spec['title']}",
        "",
        "状態: 生成待ち",
        "",
        "本文内容と一致する画像だけを次工程でChatGPT Images 2.0により生成します。現時点では画像ファイルを作らず、本文にも未生成画像へのリンクを置きません。共通画像の使い回しと表示キャプションは行いません。",
    ]
    for index, item in enumerate(spec["image_plan"], 1):
        parts.extend(
            [
                "",
                f"## {index}. {item['filename']}",
                "",
                f"- 種別: {item['type']}",
                f"- 配置予定: {item['placement']}",
                f"- 目的: {item['purpose']}",
                f"- 生成状態: pending",
                f"- プロンプト: {item['prompt']}",
            ]
        )
    return "\n".join(parts) + "\n"


def build_book_info(spec: dict[str, Any], counts: dict[str, int]) -> str:
    return f"""# 書籍情報

- タイトル: {spec['title']}
- サブタイトル: {spec['subtitle']}
- 著者名: {spec['author']}
- 言語: 日本語
- 形式: Kindle電子書籍・文字中心
- 表示文字数: {sum(counts.values()):,}字
- 原稿構成: はじめに、5章30節、おわりに
- 画像: 計画済み・生成待ち
- 表紙: 生成待ち
- EPUB: 生成待ち

## 想定読者

{bullets(spec['target_reader'])}

## 本書の約束

{punctuate(spec['promise'])}

## 内容上の注意

{bullets(spec['safety_rules'])}

本書は一般的な情報と実践の整理を目的とし、読者個人への専門的助言を代替しません。本文の事例は架空の複合事例です。
"""


def build_categories(spec: dict[str, Any]) -> str:
    return f"""# ジャンル・キーワード

## カテゴリ候補

{bullets(spec['kdp']['categories'])}

## 検索キーワード候補

{numbered(spec['kdp']['keywords'])}

## 登録時の注意

- KDP管理画面で実際に選択可能なカテゴリ名を公開直前に確認する
- 商標や特定の商品名へ不当に便乗しない
- 本文にない効果や結果をキーワードで約束しない
"""


def build_description_html(spec: dict[str, Any]) -> str:
    problem_items = "".join(f"<li>{escape(item)}</li>" for item in spec["reader_problem"])
    benefit_items = "".join(
        f"<li>{escape(item)}</li>"
        for item in [
            spec["promise"],
            "各場面で使える行動手順とチェックリスト",
            "失敗時に戻る位置が分かる落とし穴対策",
            "自分の条件との差を考えられる架空の複合事例",
        ]
    )
    reader_items = "".join(f"<li>{escape(item)}</li>" for item in spec["target_reader"])
    toc_items = "".join(
        f"<li>第{chapter['number']}章 {escape(chapter['title'])}</li>"
        for chapter in spec["chapters"]
    )
    return f"""<h2>{escape(spec['kdp']['sales_hook'])}</h2>
<ul>{problem_items}</ul>
<h3>迷いを、次にできる小さな作業へ</h3>
<p>{escape(spec['differentiation'])}</p>
<h3>本書で得られること</h3>
<ul>{benefit_items}</ul>
<h3>こんな方におすすめ</h3>
<ul>{reader_items}</ul>
<h3>今日から始められます</h3>
<p>{escape(spec['closing']['first_action'])}</p>
<h3>目次</h3>
<ul><li>はじめに</li>{toc_items}<li>おわりに</li></ul>
"""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def build_quality_report(
    spec: dict[str, Any],
    counts: dict[str, int],
    duplicates: list[str],
    repetition: dict[str, object],
    unrelated_faq_safety_hits: int,
) -> str:
    rows = "\n".join(f"| {name} | {count:,} |" for name, count in counts.items())
    total = sum(counts.values())
    return f"""# 品質チェックレポート（本文完成・資産生成前）

- 書籍: {spec['title']}
- 表示文字数: {total:,}字
- 文字数ゲート: {'PASS' if 95_000 <= total <= 105_000 else 'FAIL'}
- 章・節: 5章30節
- 同一長文段落の重複: {len(duplicates)}件
- 同一文の余剰反復率: {float(repetition['duplicate_extra_ratio']) * 100:.2f}%
- 同一文の余剰反復文字数: {int(repetition['duplicate_extra_chars']):,}字
- 無関係な旧FAQ安全文: {unrelated_faq_safety_hits}件
- 表示キャプション禁止語の本文混入: なし
- 画像: pending
- 表紙PNG/JPEG: pending
- EPUB: pending
- 最終品質チェック: pending

| ファイル | 表示文字数 |
|---|---:|
{rows}

## 現段階の判定

本文、リサーチ、企画、アウトライン、画像計画、KDPメタデータ3点は生成済みです。画像、表紙、EPUBを実生成していないため、validate_ebook_batch.py の最終パッケージ判定はまだ合格になりません。次工程で資産生成後に再検証します。
"""


def build_progress(
    spec: dict[str, Any],
    counts: dict[str, int],
    created_at: str,
    repetition: dict[str, object],
    unrelated_faq_safety_hits: int,
) -> dict[str, Any]:
    return {
        "book_name": spec["slug"],
        "title": spec["title"],
        "subtitle": spec["subtitle"],
        "author": spec["author"],
        "status": "manuscript_complete_assets_pending",
        "created_at": created_at,
        "target_chars": 100_000,
        "pass_range": {"min": 95_000, "max": 105_000},
        "initial_questions": spec["phase0"],
        "edition_policy": {
            "text_edition": "complete_text_only",
            "manga_included": False,
        },
        "steps": {
            "0_theme_research": {"status": "done"},
            "1_planning": {"status": "done"},
            "2_outline": {"status": "done"},
            "3_project": {"status": "done"},
            "4_manuscript": {"status": "done"},
            "5_image_plan": {"status": "done"},
            "6_images": {"status": "pending"},
            "7_metadata": {
                "status": "in_progress",
                "documents": "done",
                "cover_png": "pending",
                "cover_jpg": "pending",
            },
            "8_quality_check": {"status": "pending"},
        },
        "char_counts": {"total": sum(counts.values()), **counts},
        "manuscript_quality": {
            "duplicate_extra_chars": repetition["duplicate_extra_chars"],
            "duplicate_extra_ratio": repetition["duplicate_extra_ratio"],
            "repeat_ratio_limit": 0.05,
            "unrelated_faq_safety_hits": unrelated_faq_safety_hits,
            "duplicate_long_paragraphs": 0,
        },
        "images": {
            "planned": len(spec["image_plan"]),
            "generated": 0,
            "status": "pending",
            "plan": "images/image_plan.md",
        },
        "cover": {"png": "pending", "jpg": "pending"},
        "epub": {"status": "pending", "file": None},
        "sources": spec["sources"],
        "publication_boundary": "KDP申請・公開は未実施。実行にはオーナーの明示承認が必要。",
    }


def generate_package(
    spec: dict[str, Any],
    output_root: Path,
    minimum: int,
    maximum: int,
    target: int,
) -> dict[str, Any]:
    if not minimum <= target <= maximum:
        raise SpecError("target must be within the minimum and maximum range")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    book_dir = output_root / spec["slug"]
    if book_dir.exists():
        raise SpecError(f"output already exists: {book_dir}")

    manuscripts = build_manuscripts(spec, target, maximum)
    counts = {name: len(visible_text(text)) for name, text in manuscripts.items()}
    total = sum(counts.values())
    if set(manuscripts) != set(EXPECTED_MANUSCRIPTS):
        raise SpecError("generated manuscript filenames do not match batch validator")
    if not minimum <= total <= maximum:
        raise SpecError(
            f"visible character gate failed: {total:,} not in {minimum:,}--{maximum:,}"
        )
    duplicates = paragraph_duplicates(manuscripts)
    if duplicates:
        raise SpecError(f"duplicate long paragraphs detected: {len(duplicates)}")
    validator_paragraph_duplicates = duplicate_long_paragraphs(
        list(manuscripts.values())
    )
    if validator_paragraph_duplicates:
        raise SpecError(
            "validator detected duplicate long paragraphs: "
            f"{len(validator_paragraph_duplicates)}"
        )
    repetition = sentence_repetition_metrics(list(manuscripts.values()))
    if float(repetition["duplicate_extra_ratio"]) >= 0.05:
        raise SpecError(
            "sentence repetition gate failed: "
            f"{float(repetition['duplicate_extra_ratio']) * 100:.2f}%"
        )
    unrelated_faq_safety_hits = sum(
        text.count("影響が大きい判断では「") for text in manuscripts.values()
    )
    if unrelated_faq_safety_hits:
        raise SpecError(
            f"legacy unrelated FAQ safety text remains: {unrelated_faq_safety_hits}"
        )
    banned = [
        name
        for name, text in manuscripts.items()
        if "<figcaption" in text.lower() or "図解:" in text or "図解：" in text
    ]
    if banned:
        raise SpecError(f"banned visible image captions found in: {', '.join(banned)}")

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory(prefix=f".{spec['slug']}-", dir=output_root) as temp:
        staging = Path(temp) / spec["slug"]
        write_text(staging / "_research" / "theme_research.md", build_research(spec))
        write_text(staging / "project.md", build_project(spec))
        write_text(staging / "manuscript" / "_outline.md", build_outline(spec))
        for filename, markdown in manuscripts.items():
            write_text(staging / "manuscript" / filename, markdown)
        write_text(staging / "images" / "image_plan.md", build_image_plan(spec))
        write_text(
            staging / "KDP出版用" / "書籍情報.md", build_book_info(spec, counts)
        )
        write_text(
            staging / "KDP出版用" / "ジャンル・キーワード.md",
            build_categories(spec),
        )
        write_text(
            staging / "KDP出版用" / "書籍紹介文_HTML.html",
            build_description_html(spec),
        )
        write_text(
            staging / "final_quality_report.md",
            build_quality_report(
                spec,
                counts,
                duplicates,
                repetition,
                unrelated_faq_safety_hits,
            ),
        )
        write_text(
            staging / "progress.json",
            json.dumps(
                build_progress(
                    spec,
                    counts,
                    created_at,
                    repetition,
                    unrelated_faq_safety_hits,
                ),
                ensure_ascii=False,
                indent=2,
            ),
        )
        staging.rename(book_dir)

    return {
        "slug": spec["slug"],
        "book_dir": str(book_dir),
        "visible_char_count": total,
        "char_gate": minimum <= total <= maximum,
        "chapter_counts": counts,
        "duplicate_long_paragraphs": len(duplicates),
        "duplicate_extra_chars": repetition["duplicate_extra_chars"],
        "duplicate_extra_ratio": repetition["duplicate_extra_ratio"],
        "unrelated_faq_safety_hits": unrelated_faq_safety_hits,
        "images": "pending",
        "cover": "pending",
        "epub": "pending",
    }


def sample_spec() -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for chapter_number in range(1, 6):
        sections: list[dict[str, Any]] = []
        for section_number in range(1, 7):
            tag = f"{chapter_number}-{section_number}"
            sections.append(
                {
                    "number": section_number,
                    "title": f"検証項目{tag}を扱う",
                    "core_message": f"項目{tag}では事実を確認してから小さく行動する",
                    "why_it_matters": f"項目{tag}の前提を飛ばすと判断の修正が難しくなる",
                    "scene": f"架空の担当者が場面{tag}で複数の情報を同時に受け取った",
                    "explanation_points": [
                        f"項目{tag}の観察事実を分ける",
                        f"項目{tag}の判断者を確認する",
                        f"項目{tag}の期限を確認する",
                        f"項目{tag}の例外条件を確認する",
                    ],
                    "action_steps": [
                        f"項目{tag}の現状を一文で記録する",
                        f"項目{tag}の公式情報を確認する",
                        f"項目{tag}の相談相手を決める",
                        f"項目{tag}を小さく試す",
                        f"項目{tag}の結果を見直す",
                    ],
                    "pitfalls": [
                        f"項目{tag}を印象だけで決める",
                        f"項目{tag}の期限を確認しない",
                        f"項目{tag}を一人で抱える",
                    ],
                    "case_study": {
                        "profile": f"場面{tag}を担当する40代の架空人物",
                        "situation": f"場面{tag}で情報不足のまま判断を求められた",
                        "decision": f"場面{tag}の事実を分けて関係者へ確認した",
                        "outcome": f"場面{tag}の未確認事項が見え、次の担当を決められた",
                    },
                    "faqs": [
                        {
                            "question": f"項目{tag}はすぐ決めるべきですか",
                            "answer": f"項目{tag}の期限と影響を先に確認します",
                        },
                        {
                            "question": f"項目{tag}を誰に相談しますか",
                            "answer": f"項目{tag}の責任範囲に合う窓口を選びます",
                        },
                        {
                            "question": f"項目{tag}で迷ったらどうしますか",
                            "answer": f"項目{tag}の最後に確認できた事実へ戻ります",
                        },
                    ],
                    "checklist": [
                        f"項目{tag}の事実を記録した",
                        f"項目{tag}の期限を確認した",
                        f"項目{tag}の判断者を確認した",
                        f"項目{tag}の相談先を確認した",
                        f"項目{tag}の見直し日を決めた",
                    ],
                    "reflection": f"項目{tag}で自分がまだ確認していない条件は何か",
                }
            )
        chapters.append(
            {
                "number": chapter_number,
                "title": f"検証用第{chapter_number}章",
                "goal": f"第{chapter_number}章の六場面で判断手順を練習する",
                "chapter_case": f"架空の担当者が第{chapter_number}章の課題を順に整理する",
                "sections": sections,
            }
        )
    return {
        "slug": "sample-theme-ebook",
        "source_rank": 99,
        "title": "検証用テーマ実践書",
        "subtitle": "最小仕様から十万字原稿を安全に組み立てる",
        "author": "Yuichi",
        "theme": "日常の判断を小さな手順へ分ける",
        "target_reader": ["複数の情報を整理したい初心者"],
        "reader_problem": ["何から確認すべきか分からない", "一人で判断を抱えてしまう"],
        "promise": "読者が事実を分けて次の一歩を決められるようにする",
        "differentiation": "30の固有場面を使い、判断と復帰の道具を練習する",
        "phase0": {
            "ui": "delegated_by_user",
            "theme_handling": "入力内容を絞り込んで進める",
            "target_reader": "初心者・これから始める人",
            "book_type": "実践書・手順書",
            "tone": "やさしいです・ます調",
            "length": "約100,000字",
            "image_density": "標準（章ごとに数点）",
        },
        "safety_rules": ["影響が大きい判断は公式情報と専門家へ確認する"],
        "sources": [
            {
                "title": "検証用公開情報",
                "url": "https://example.com/reference",
                "note": "生成テストで参照情報の出力形式を確認する",
            }
        ],
        "intro": {
            "opening_scene": "朝、複数の連絡を前に何から手を付けるか迷っている",
            "misconception": "早く決めることがいつも良い判断だと思い込んでいる",
            "reading_guide": ["一日一節ずつ試す", "関係者とチェック項目を共有する"],
        },
        "chapters": chapters,
        "closing": {
            "future_scene": "迷った時に確認する順序と相談相手が見えている",
            "first_action": "今日の迷いを事実と推測の二列に分けて書く",
            "author_message": "小さな確認を積み重ね、自分のペースで前へ進んでください",
        },
        "image_plan": [
            {
                "filename": f"chapter_{number:02d}.png",
                "type": "illustration",
                "placement": f"第{number}章冒頭",
                "purpose": f"第{number}章の判断場面を視覚化する",
                "prompt": f"第{number}章の架空の担当者が情報を整理する日本のアニメ調挿絵",
            }
            for number in range(1, 6)
        ],
        "kdp": {
            "categories": ["ビジネス・経済", "自己啓発"],
            "keywords": [
                "判断整理",
                "実践手順",
                "初心者",
                "チェックリスト",
                "問題解決",
                "情報整理",
                "行動計画",
            ],
            "sales_hook": "迷いを三十分の作業へ変える",
        },
    }


def run_self_test(minimum: int, maximum: int, target: int) -> int:
    with tempfile.TemporaryDirectory(prefix="theme-ebook-selftest-") as temp:
        root = Path(temp)
        spec_path = root / "sample_spec.json"
        spec_path.write_text(
            json.dumps(sample_spec(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        spec = load_spec(spec_path)
        result = generate_package(spec, root / "output", minimum, maximum, target)
        validator_report = validate_book(Path(result["book_dir"]), minimum, maximum)
        allowed_missing = {
            "KDP出版用/cover.png",
            "KDP出版用/cover.jpg",
            "KDP出版用/*.epub",
        }
        unexpected_missing = sorted(
            set(validator_report["missing_files"]) - allowed_missing
        )
        if (
            not validator_report["char_gate"]
            or unexpected_missing
            or validator_report["missing_images"]
            or validator_report["banned_caption_hits"]
            or not validator_report["repetition_gate"]
            or not validator_report["paragraph_duplicate_gate"]
            or not validator_report["faq_relevance_gate"]
        ):
            raise SpecError(
                "self-test did not align with validate_ebook_batch.py: "
                + json.dumps(validator_report, ensure_ascii=False)
            )
        result["sample_spec_json"] = "parsed"
        result["expected_pending_assets"] = ["images", "cover", "epub"]
        result["validator_alignment"] = {
            "char_gate": validator_report["char_gate"],
            "unexpected_missing_files": unexpected_missing,
            "missing_images": validator_report["missing_images"],
            "banned_caption_hits": validator_report["banned_caption_hits"],
            "duplicate_extra_ratio": validator_report["sentence_repetition"][
                "duplicate_extra_ratio"
            ],
            "repetition_gate": validator_report["repetition_gate"],
            "duplicate_long_paragraphs": validator_report[
                "duplicate_long_paragraphs"
            ],
            "unrelated_faq_safety_hits": validator_report[
                "unrelated_faq_safety_hits"
            ],
            "expected_final_gate": False,
            "reason": "cover and EPUB intentionally pending",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a nonfiction theme-to-ebook package from a JSON spec."
    )
    parser.add_argument("spec", nargs="?", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--min", dest="minimum", type=int, default=95_000)
    parser.add_argument("--max", dest="maximum", type=int, default=105_000)
    parser.add_argument("--target", type=int, default=100_000)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.self_test:
            return run_self_test(args.minimum, args.maximum, args.target)
        if args.spec is None:
            parser.error("spec is required unless --self-test is used")
        spec = load_spec(args.spec.resolve())
        result = generate_package(
            spec, args.output_root, args.minimum, args.maximum, args.target
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SpecError as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
