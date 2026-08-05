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

## 今後の予定

- `ranking_fetcher.py`: 楽天ウェブサービス(公式API)からジャンル別ランキング・商品検索データを毎日取得してSQLiteに蓄積
  - 要: 楽天ウェブサービスのアプリID (https://webservice.rakuten.co.jp/ で無料発行)
- `selector.py`: 蓄積したランキングから「急上昇 × 高料率 × 高レビュー × 自分のROOMの得意ジャンル」でスコアリングし、毎朝の投稿候補リストを生成
- 週次で analyze_room.py の結果を蓄積し、どの商品タイプが反応が良いかを選定スコアにフィードバック
