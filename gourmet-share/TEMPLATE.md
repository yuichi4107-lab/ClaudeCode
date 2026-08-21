# 地図ベース共有アプリ テンプレート

グルメシェアをベースに、テーマを変えて新しいアプリをすぐに作成するためのガイド。

---

## 概要

このテンプレートは以下の機能を持つ「地図ベースのスポット共有アプリ」を任意のテーマで作成できる。

### テンプレートで提供される機能
- メールマジックリンク認証（Supabase Auth）
- 地図表示 + カテゴリ別カラーピン（Leaflet + OpenStreetMap）
- スポット登録（国土地理院ジオコーディング、番地レベル精度）
- 2軸の価格帯/評価（昼/夜 → 任意の2軸に変更可能）
- スポット検索（名前・カテゴリ・地名対応、複数結果フィット表示）
- フィルタ（カテゴリ・時間帯/軸・価格帯/評価）
- マイタウン設定（ログイン時に自分の街を初期表示）
- 投稿者コメント
- リアクション + コメント（他人の投稿のみ）
- 投稿者による編集・削除
- PWA対応（スマホホーム画面追加可能）
- Vercelデプロイ（無料）

### 技術スタック
- Next.js 16 + React 19 + TypeScript + Tailwind CSS 4
- Supabase（認証 + PostgreSQL + PostGIS + RLS）
- Leaflet + OpenStreetMap（地図）
- 国土地理院API（ジオコーディング）
- Vercel（ホスティング）

### ランニングコスト
**月額0円**（全て無料枠内で運用可能）

---

## テーマ変更時に編集が必要なファイル一覧

### 1. テーマ定義ファイル（最重要）

#### `src/lib/constants.ts`
カテゴリ、色、価格帯/評価軸、リアクション定義を全てここで管理。

```typescript
// ========== テーマに合わせて変更 ==========

// カテゴリ一覧（グルメの場合: ジャンル）
export const CATEGORIES = [
  '神社仏閣', '自然景観', '博物館', 'テーマパーク', '温泉',
  '歴史建造物', '展望スポット', 'ビーチ', '公園', 'その他',
] as const;
export type Category = (typeof CATEGORIES)[number];

// カテゴリ別ピンカラー
export const CATEGORY_COLORS: Record<Category, string> = {
  '神社仏閣': '#C62828',
  '自然景観': '#2E7D32',
  // ... 全カテゴリに色を設定
};

// 評価軸1（グルメの場合: 昼の価格帯）
export const AXIS1_OPTIONS = ['無料', '~500', '500~1,000', '1,000~3,000', '3,000~'] as const;
export type Axis1 = (typeof AXIS1_OPTIONS)[number];
export const AXIS1_LABEL = '入場料';

// 評価軸2（グルメの場合: 夜の価格帯）
export const AXIS2_OPTIONS = ['30分以内', '1時間', '半日', '1日', '1泊以上'] as const;
export type Axis2 = (typeof AXIS2_OPTIONS)[number];
export const AXIS2_LABEL = '所要時間';

// リアクション定義
export const BEFORE_REACTIONS = [
  { key: 'want_to_go', emoji: '🙋', label: '行きたい！' },
  { key: 'interested', emoji: '👀', label: '気になる' },
];
export const AFTER_REACTIONS = [
  { key: 'great_view', emoji: '😍', label: '景色が最高' },
  { key: 'photogenic', emoji: '📸', label: '映える' },
  // ... テーマに合ったリアクションを定義
];
```

### 2. DB定義

#### `supabase/migrations/001_initial.sql`
テーブル名・カラム名はそのまま使えるが、以下を変更:
- `genre` → カテゴリカラム（名前はそのまま流用可能）
- `price_range` / `lunch_price_range` / `dinner_price_range` → テーマに合った軸名に変更可能（ただしコード側も合わせる）

#### `src/lib/supabase/types.ts`
DB型定義。カラム追加・変更時に更新。

### 3. UIテキスト・ラベル

#### `src/app/layout.tsx`
```
title: 'アプリ名'
description: 'アプリの説明'
```

#### `src/app/login/page.tsx`
```
タイトル: 'アプリ名'
サブタイトル: 'キャッチコピー'
```

#### `src/components/layout/BottomNav.tsx`
```
ナビゲーション項目のラベルとアイコン
```

#### `public/manifest.json`
```
name, short_name, description
```

### 4. 必要に応じて変更

| ファイル | 変更内容 |
|----------|----------|
| `src/components/restaurant/RestaurantForm.tsx` | フォームのフィールド名・ラベル |
| `src/components/restaurant/RestaurantCard.tsx` | カード表示のラベル |
| `src/app/(main)/restaurant/[id]/page.tsx` | 詳細ページの表示 |
| `src/app/(main)/restaurant/[id]/edit/page.tsx` | 編集ページのフィールド |
| `src/components/map/FilterPanel.tsx` | フィルタのラベル |
| `src/components/reaction/ReactionPicker.tsx` | リアクションのカテゴリ見出し |
| `src/app/(main)/list/page.tsx` | 一覧ページのタイトル |

---

## 新規テーマでの作成手順

### ステップ1: プロジェクト複製
```bash
cp -r gourmet-share <新プロジェクト名>
cd <新プロジェクト名>
rm -rf .git node_modules .next .vercel
```

### ステップ2: テーマ定義を変更
`src/lib/constants.ts` のカテゴリ、色、評価軸、リアクションを新テーマに書き換え。

### ステップ3: UIテキストを変更
- `src/app/layout.tsx` → アプリ名・説明
- `src/app/login/page.tsx` → タイトル・キャッチコピー
- `src/components/layout/BottomNav.tsx` → ナビラベル
- `public/manifest.json` → PWA名

### ステップ4: Supabaseプロジェクト作成
1. supabase.com で新規プロジェクト作成
2. SQL Editorで `supabase/migrations/001_initial.sql` を実行
3. 追加カラムがあればALTER TABLEで追加
4. Settings > API から URL と anon key を取得
5. `.env.local` に設定

### ステップ5: インストール・起動
```bash
npm install
npm run dev
```

### ステップ6: デプロイ
```bash
git init && git add -A && git commit -m "Initial commit"
gh repo create <名前> --public --source=. --push
npx vercel --yes --prod \
  -e NEXT_PUBLIC_SUPABASE_URL=<URL> \
  -e NEXT_PUBLIC_SUPABASE_ANON_KEY=<ANON_KEY> \
  -e SUPABASE_SERVICE_ROLE_KEY=<SERVICE_ROLE_KEY>
```

### ステップ7: Supabase認証URL設定
Settings > URL Configuration で:
- Site URL: `https://<プロジェクト名>.vercel.app`
- Redirect URLs: `https://<プロジェクト名>.vercel.app/auth/callback`

---

## テーマ例と変更箇所

### 例1: 観光スポット共有
| 項目 | グルメシェア | 観光スポット |
|------|-------------|-------------|
| アプリ名 | グルメシェア | スポットシェア |
| カテゴリ | 和食, 中華, イタリアン... | 神社仏閣, 自然景観, 博物館... |
| 軸1 | 昼の価格帯 | 入場料 |
| 軸2 | 夜の価格帯 | 所要時間 |
| リアクション | おいしかった, 量が多い... | 景色が最高, 映える, 子連れOK... |

### 例2: 公園・遊び場共有
| 項目 | グルメシェア | 公園シェア |
|------|-------------|-----------|
| アプリ名 | グルメシェア | パークシェア |
| カテゴリ | 和食, 中華... | 公園, 遊園地, 水遊び場... |
| 軸1 | 昼の価格帯 | 料金 |
| 軸2 | 夜の価格帯 | 対象年齢 |
| リアクション | おいしかった... | 子供が喜んだ, 広い, 駐車場あり... |

### 例3: ワークスペース共有
| 項目 | グルメシェア | ワークスペース |
|------|-------------|--------------|
| アプリ名 | グルメシェア | ワークシェア |
| カテゴリ | 和食, 中華... | カフェ, コワーキング, 図書館... |
| 軸1 | 昼の価格帯 | 利用料金 |
| 軸2 | 夜の価格帯 | 滞在時間目安 |
| リアクション | おいしかった... | WiFi速い, 電源あり, 静か... |

---

## ファイル構成

```
src/
├── app/
│   ├── layout.tsx              # ルートレイアウト（アプリ名）
│   ├── page.tsx                # / → /map リダイレクト
│   ├── globals.css             # グローバルCSS
│   ├── login/page.tsx          # ログインページ（タイトル）
│   ├── auth/callback/route.ts  # 認証コールバック（変更不要）
│   ├── (main)/
│   │   ├── layout.tsx          # メインレイアウト（変更不要）
│   │   ├── map/page.tsx        # マップページ
│   │   ├── list/page.tsx       # リストページ
│   │   ├── add/page.tsx        # 登録ページ
│   │   ├── profile/page.tsx    # プロフィール（マイタウン）
│   │   └── restaurant/[id]/
│   │       ├── page.tsx        # 詳細ページ
│   │       └── edit/page.tsx   # 編集ページ
│   └── api/
│       ├── geocode/route.ts    # ジオコーディング（変更不要）
│       └── restaurants/[id]/route.ts  # CRUD API（変更不要）
├── components/
│   ├── layout/BottomNav.tsx    # 下部ナビ（ラベル）
│   ├── map/
│   │   ├── MapContainer.tsx    # 地図コンテナ（変更不要）
│   │   ├── MapInner.tsx        # 地図本体（変更不要）
│   │   ├── SearchBar.tsx       # 検索バー（変更不要）
│   │   └── FilterPanel.tsx     # フィルタ（ラベル）
│   ├── restaurant/
│   │   ├── RestaurantForm.tsx  # 登録フォーム（フィールド）
│   │   └── RestaurantCard.tsx  # カード（表示ラベル）
│   └── reaction/
│       └── ReactionPicker.tsx  # リアクション（見出し）
├── hooks/
│   ├── useMyTown.ts            # マイタウン（変更不要）
│   ├── useReactions.ts         # リアクション（変更不要）
│   └── useRestaurants.ts       # データ取得（変更不要）
└── lib/
    ├── constants.ts            # ★テーマ定義（最重要）
    ├── map-utils.ts            # 地図ユーティリティ（変更不要）
    └── supabase/
        ├── client.ts           # Supabaseクライアント（変更不要）
        ├── server.ts           # Supabaseサーバー（変更不要）
        └── types.ts            # DB型定義（カラム変更時のみ）
```

**変更不要** と記載されたファイルはテーマを変えても一切修正不要。
**★テーマ定義** の `constants.ts` が最も重要で、ここを変えるだけで大部分が切り替わる。
