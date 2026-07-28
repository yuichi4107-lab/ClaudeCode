# Saxo Bank OpenAPI Sim環境セットアップ手順

> 工程1成果物 — オーナー作業の手順書（実測10〜15分）
> 作成日: 2026-04-12

ai-trade-system のFXアダプターをサクソバンクOpenAPIのSim（シミュレーション）環境で動かすための手順。
本番口座（Live）への切り替えは [後述](#live移行) の通り別工程。

---

## 0. 前提

- Saxo Developer Sim アカウント（Live取引口座とは別）が必要
- コマンドラインは **bash** 前提（WSL2、Git Bash、Mac Terminal、Linux）。WindowsのPowerShellの場合はWSL2/Git Bashを推奨
- すでに Sim 用 Personal Access Token を取得済みの場合は [4. .env 設定](#4-env-設定) から

---

## 1. Saxo Developer Sim アカウント作成

1. ブラウザで https://www.developer.saxo/openapi/appmanagement にアクセス
2. 「Sign up」または「Create Account」リンクから Sim 用アカウントを作成
   - クレジットカード等の支払い情報は不要
3. 入力したメールアドレスに届く確認メールから有効化

---

## 2. 24時間Personal Access Tokenの取得

1. Developer Portal にログイン: https://www.developer.saxo/openapi/appmanagement
2. 上部メニューの **「Get 24 Hour Token」** タブをクリック
   - URL: https://www.developer.saxo/openapi/token
3. 利用規約画面で内容確認（要点）
   - 動作確認・探索目的に限る
   - 脆弱性探索・過剰APIコール禁止
   - 5台以上から同時利用禁止
   - Tokenは個人専用、共有禁止
4. 緑のボタン **「I HAVE READ AND ACCEPT THE TERMS」** をクリック
5. 表示された **access_token**（`eyJhbGciOiJ...` で始まる長文字列）をコピー

> ⚠️ **24時間で失効** する。失効したら同じ手順で再取得して `.env` の `SAXO_SIM_TOKEN` を上書き。

---

## 3. Account Key / Account ID の取得

Tokenを使って、Account情報を以下のコマンドで取得:

```bash
TOKEN="<手順2でコピーしたToken>"
curl -s -H "Authorization: Bearer $TOKEN" \
  https://gateway.saxobank.com/sim/openapi/port/v1/clients/me | python -m json.tool
```

レスポンスから以下4項目を控える（次の手順4で `.env` に貼る）:

| JSONキー | .env変数 | 例 |
|---|---|---|
| `ClientKey` | `SAXO_SIM_CLIENT_KEY` | `g1tgTuNj7PmNzC6PS21LAg==` |
| `DefaultAccountKey` | `SAXO_SIM_ACCOUNT_KEY` | （ClientKeyと同じことが多い） |
| `DefaultAccountId` | `SAXO_SIM_ACCOUNT_ID` | `22131037` |
| `DefaultCurrency` | `SAXO_SIM_DEFAULT_CURRENCY` | `EUR` |

> 📝 Sim口座のデフォルト通貨はEUR、初期残高は1,000,000 EUR（仮想資金）

---

## 4. .env 設定

`ai-trade-system/.env` に以下を追記（`<...>` を実値で置換）:

```bash
# Saxo Bank OpenAPI - Sim環境
SAXO_SIM_TOKEN=<手順2でコピーしたToken>
SAXO_SIM_BASE_URL=https://gateway.saxobank.com/sim/openapi
SAXO_SIM_CLIENT_KEY=<手順3で取得>
SAXO_SIM_ACCOUNT_KEY=<手順3で取得（通常ClientKeyと同じ）>
SAXO_SIM_ACCOUNT_ID=<手順3で取得>
SAXO_SIM_DEFAULT_CURRENCY=<手順3で取得（通常EUR）>
```

---

## 5. 接続テスト

`.env`設定後、以下4本のコマンドが全て200を返せば疎通OK:

```bash
source .env
TOKEN=$SAXO_SIM_TOKEN
BASE=$SAXO_SIM_BASE_URL

# (1) ユーザー情報
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/port/v1/users/me" | python -m json.tool

# (2) 残高
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/port/v1/balances/me" | python -m json.tool

# (3) USD/JPY 現在値
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/trade/v1/infoprices?AssetType=FxSpot&Uic=42" | python -m json.tool

# (4) USD/JPY 日足直近10本
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/chart/v3/charts?AssetType=FxSpot&Uic=42&Horizon=1440&Count=10" | python -m json.tool
```

> ⚠️ Chart APIは **v3**（`chart/v3/charts`）。v1は404を返す。

---

## 6. 主要エンドポイント一覧

| 用途 | パス | 備考 |
|---|---|---|
| ユーザー情報 | `/port/v1/users/me` | |
| クライアント情報 | `/port/v1/clients/me` | ClientKey, DefaultAccountKey |
| 口座一覧 | `/port/v1/accounts/me` | |
| 残高 | `/port/v1/balances/me` | |
| 銘柄検索 | `/ref/v1/instruments?Keywords=USDJPY&AssetTypes=FxSpot` | UIC取得 |
| 現在値 | `/trade/v1/infoprices?AssetType=FxSpot&Uic={uic}` | Bid/Ask/Mid |
| OHLCV | `/chart/v3/charts?AssetType=FxSpot&Uic={uic}&Horizon={min}&Count={n}` | v3必須 |
| 注文発注 | `POST /trade/v2/orders` | |
| 未約定注文 | `/port/v1/orders/me` | |
| ポジション | `/port/v1/positions/me` | |

---

## 7. 通貨ペアUIC一覧（FxSpot）

接続テスト時に確認した実値:

| Symbol | UIC | Description |
|---|---|---|
| USDJPY | **42** | US Dollar / Japanese Yen |
| EURJPY | **18** | Euro / Japanese Yen |
| EURUSD | (要確認) | Euro / US Dollar |
| GBPJPY | (要確認) | British Pound / Japanese Yen |

UIC取得は `/ref/v1/instruments?Keywords={symbol}&AssetTypes=FxSpot` で。

---

## 8. Token失効時の再取得

1. https://www.developer.saxo/openapi/token を開く
2. 「I HAVE READ AND ACCEPT THE TERMS」を再度クリック
3. 新しいTokenをコピーして `.env` の `SAXO_SIM_TOKEN` を上書き

---

## Live移行

Sim動作確認後、本番環境（Live）に移行する場合の手順:

1. https://www.home.saxo/ja-jp/accounts で取引口座を開設
2. 口座開設後、API契約書に同意
3. Developer Portal で Live Application を登録（OAuth用 App Key/Secret発行）
4. OAuth Authorization Code Flow で `refresh_token` 取得
5. `SAXO_LIVE_*` 系の変数を `.env` に追加
6. `SAXO_LIVE_BASE_URL=https://gateway.saxobank.com/openapi`（"sim/" がない）

> ⚠️ Live OpenAPI の利用条件（最低入金額・手数料）について公式ページと二次情報サイトで食い違いあり。
> Sim完了後、口座開設→API申請の段階で現場確認すること。条件が厳しければ別ブローカーへの切替判断を行う。

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| 401 Unauthorized | Token失効・誤コピー | Token再取得、Bearerプレフィックス確認 |
| 404 Not Found（chart） | v1を叩いている | v3に変更 |
| 空レスポンス | URLパス末尾の `/` で挙動差異 | 手順5の通り `/` なしで実行 |
| Empty Data（infoprices） | UICが間違い | `/ref/v1/instruments` で再確認 |
| Market State: Closed | 市場閉鎖時間 | FX市場は土日休み（JST月7時〜土6時） |

---

## 参考リンク

- 公式: https://www.home.saxo/ja-jp/platforms/api
- Developer Portal: https://www.developer.saxo/
- API Reference: https://www.developer.saxo/openapi/referencedocs
- Help Center: https://openapi.help.saxo/hc/en-us
- Pythonライブラリ（参考）: https://github.com/hootnot/saxo_openapi
