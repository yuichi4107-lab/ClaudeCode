---
name: jibunshi-ebook-manga-service
description: 祖父母・両親・シニアの自分史を、完全文字版電子書籍と完全漫画版電子書籍の二本立てで受注制作するためのYNFactory専用スキル。LP/QR導線、受注フォルダ作成、ヒアリング、同意確認、theme-to-ebook / theme-to-ebook-to-manga / ebook-to-manga への接続、納品前QAまで扱う。ユーザーが「自分史」「祖父母向け」「両親の人生を本にする」「文字版と漫画版」「個別受注」と言ったとき、絵本KDPのQR/LP導線から次の商品として自分史サービスを案内するとき、または受注後に注文フォルダを作り制作を開始するときに使う。
---

# 自分史 文字版＋フル漫画版サービス

祖父母・両親・シニア層の人生を、家族に残す電子書籍として制作する。

このスキルは本文生成や漫画画像生成を再実装しない。受注、個人情報確認、制作ブリーフ、既存スキルへの接続、納品前QAを管理する。

## 使用タイミング

- ユーザーが「自分史」「祖父母向け」「両親の人生を本にする」「文字版と漫画版」「個別受注」と言ったとき
- 絵本KDPのQR/LP導線から、次の商品として自分史サービスを作るとき
- 受注後に注文フォルダを作り、制作を開始するとき

## 最初に確認すること

1. 日付をツールで確認する
2. `.company/secretary/HANDOFF.md` を読む
3. `.company/secretary/todos/` の最新TODOを読む
4. 関連ルールとして `AGENTS.md` とこのスキルを使う

## 標準出力

サービス本体:

```text
.company/services/jibunshi-ebook-manga/
```

注文ごとの作業場所:

```text
.company/outputs/jibunshi-orders/{order-id}/
```

完全文字版:

```text
.company/outputs/ebooks/{order-id}-text/
```

完全漫画版:

```text
.company/outputs/ebooks-manga/{order-id}-manga/
```

LP:

```text
.company/outputs/lp/jibunshi-ebook-manga/
```

## 受注フォルダ作成

注文が入ったら、以下のスクリプトで注文フォルダを作る。

```bash
python3 .company/services/jibunshi-ebook-manga/tools/create_order_package.py \
  --subject-name "主役名" \
  --buyer-name "注文者名" \
  --relationship "孫" \
  --package bundle \
  --publication-scope family_private
```

## 商品ルール

### 完全文字版

- 漫画ページを入れない
- 章末漫画、挿入漫画、漫画風ページを入れない
- 写真、年表、家系図、図解は本人・家族の希望がある場合のみ使う
- 出力は `theme-to-ebook` を使う
- `edition_policy.text_edition = complete_text_only` を制作ブリーフに残す

### 完全漫画版

- 承認済みの完全文字版をソースにする
- 全編漫画として独立して読めるようにする
- 出力は `theme-to-ebook-to-manga` を使い、下流で `ebook-to-manga` に渡す
- 漫画版タイトルは既存ルールに合わせて `マンガでわかる！{文字版タイトル}` を標準にする

## 個人情報・同意

制作前に必ず確認する:

- 主役本人が制作を知っている、または注文者に正当な代理権限がある
- 素材利用の許可
- 写真利用方針
- 実名利用方針
- 伏せる情報

公開前に必ず確認する:

- 文字版の最終承認
- 漫画版の最終承認
- 外部公開の明示承認
- KDP申請の明示承認

## 停止条件

以下の場合は制作を進めず、オーナーへ確認する。

- 本人同意または代理権限が不明
- 公開範囲が未確定
- 写真や実名利用の許可が曖昧
- 家族内で内容確認者が決まっていない
- KDP公開や外部フォーム公開など不可逆な外部操作が必要

## 品質チェック

`.company/services/jibunshi-ebook-manga/quality_checklist.md` を使う。85点未満なら修正する。

特に見ること:

- 文字版に漫画が混じっていない
- 漫画版が承認済み文字版だけから作られている
- 個人情報が公開範囲に合っている
- 納品対象に内部素材が混ざっていない
- 外部公開が未承認のまま行われていない

## 関連ファイル

- `.company/services/jibunshi-ebook-manga/README.md`
- `.company/services/jibunshi-ebook-manga/SERVICE_BLUEPRINT.md`
- `.company/services/jibunshi-ebook-manga/production_workflow.md`
- `.company/services/jibunshi-ebook-manga/intake_questions.md`
- `.company/services/jibunshi-ebook-manga/privacy_and_consent.md`
- `.company/services/jibunshi-ebook-manga/quality_checklist.md`
