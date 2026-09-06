# rakuten_room — 楽天ROOM 投稿分析・商品選定ツール

楽天ROOMの投稿成果を分析し、楽天市場の売れ筋データに基づいて投稿商品を選定するためのツール群。

## analyze_room.py — 投稿傾向分析

自分のROOM(公開ページ)から全投稿を取得し、いいね・価格帯・カテゴリ・投稿文タイプの傾向をレポートする。ログイン不要。

```bash
# 傾向レポートを表示
python rakuten_room/analyze_room.py <ROOMユーザー名>

# 投稿一覧をCSV/JSONにも出力(Excelで開ける)
python rakuten_room/analyze_room.py <ROOMユーザー名> --csv room_posts.csv --json room_posts.json
```

ユーザー名は `room.rakuten.co.jp/○○○` の `○○○` 部分。

### 取得できる指標
- アカウント統計: フォロワー数、ROOMランク、売上件数、もらった/送ったいいね数
- 投稿ごと: いいね数、投稿日時、商品価格、カテゴリ、投稿文
- 定型文投稿とオリジナル文投稿のいいね率比較
- オリジナル写真の有無(ROOMのAランク昇格条件に関係)

## suggest.py — 投稿候補リスト生成

楽天市場の売れ筋ランキング(公式API)から、ROOMと相性の良いジャンルの投稿候補トップNをスコアリングして出力する。

```bash
# 認証情報を環境変数で設定(リポジトリには書かない)
export RAKUTEN_APP_ID=<アプリID>
export RAKUTEN_ACCESS_KEY=<アクセスキー pk_...>
export RAKUTEN_ALLOWED_DOMAIN=<「許可されたWebサイト」に登録したドメイン>
export RAKUTEN_AFFILIATE_ID=<アフィリエイトID(任意)>

python rakuten_room/suggest.py            # 候補トップ10を表示 + data/suggestions/ にMarkdown保存
python rakuten_room/suggest.py --top-n 15
python rakuten_room/suggest.py --genres 215783,100804   # ジャンルを指定
```

### 仕組み
- デフォルト対象ジャンル: 日用品雑貨(215783)・インテリア(100804)・キッチン(558944)
  — analyze_room.py の分析で反応が良かった系統
- ランキングを SQLite (`data/rakuten_room.db`) に日次スナップショット保存し、
  前回との順位差から「急上昇」商品を検出(毎日実行すると精度が上がる)
- スコア = 順位(30%) + レビュー(25%) + 価格帯フィット(15%) + 期待報酬(15%) + 急上昇(15%)
- 出力にはアフィリエイトURL・投稿文のたたき台付き。
  **たたき台の「自分の言葉ポイント」は必ず書き換えてから投稿すること**(定型文はいいねが付きにくい)

### 2026年新API対応メモ
- エンドポイントは `openapi.rakuten.co.jp` 配下(旧 `app.rakuten.co.jp` は2026/5に廃止)
- `applicationId` + `accessKey` の2点認証
- Webアプリケーション型はReferer/Originチェックがあるため、
  「許可されたWebサイト」登録ドメインを `RAKUTEN_ALLOWED_DOMAIN` に設定する

## 今後の予定

- 週次で analyze_room.py の結果を蓄積し、どの商品タイプが反応が良いかを選定スコアにフィードバック
- ROOMの成果レポート(クリック・売上)を手入力できるようにしてROI基準のスコア調整
