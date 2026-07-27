# CLAUDE.md — 「知ってたつもり日本史」動画制作パイプライン

## プロジェクト概要

YouTubeチャンネル **「知ってたつもり日本史」** の教育漫画動画を制作するパイプライン。
日本史テーマから台本Markdown → Comicle用漫画CSV → YouTubeメタデータを一気通貫で生成する。

- **シリーズ名**: 歴史の敗者シリーズ（悲劇の歴史人物にフォーカス）
- **ターゲット視聴者**: 60代以上（親しみやすい表現、過度にカジュアルな言葉は避ける）
- **制作プラットフォーム**: Comicle（コミクル）で漫画形式の動画を生成
- **過去の題材**: 崇徳上皇、平将門、道鏡、平宗盛、北条高時、後醍醐天皇、源義経

---

## ディレクトリ構成

```
project-root/
├── CLAUDE.md                         ← このファイル
├── scripts/
│   ├── convert_to_csv.py             ← Step 1: Markdown → CSV（30字分割）
│   ├── add_furigana.py               ← Step 2: GPT-4.1-miniフリガナ付与
│   ├── add_furigana_local.py         ← Step 2: ルールベース代替版（API不要）
│   ├── generate_comicle_csv.py       ← Step 3: Comicle CSV生成
│   └── compare_dialogues.py          ← Step 4: 比較分析
├── references/
│   ├── script_format.md              ← 台本Markdownフォーマット仕様
│   ├── comparison_checklist.md       ← 比較分析結果の解釈ガイド
│   └── yoshitsune_thumbnail.md       ← サムネイルプロンプト参考例（源義経）
├── assets/
│   ├── 参考script.csv                ← 台本CSVの参考例（邪馬台国）
│   ├── 参考用.csv                    ← Comicle CSVの参考例
│   ├── characters/
│   │   ├── ミユ.png                  ← ミユのキャラクターデザイン
│   │   └── ヨウイチ.png              ← ヨウイチのキャラクターデザイン
│   └── templates/
│       ├── テンプレ1.png             ← 1コマ（全画面）
│       ├── テンプレ2.png             ← 2コマ（右1/3・左2/3）
│       ├── テンプレ3.png             ← 3コマ（均等3分割）
│       ├── テンプレ4.png             ← 2コマ（左2/3・右1/3）
│       └── テンプレ5.png             ← 2コマ（左右均等）
└── output/                           ← 生成物の出力先
```

---

## パイプライン全体像

```
[ユーザー] テーマ指定（例：「平清盛」）
    ↓
Step 0: 台本Markdownの作成（script_raw.md）
    ↓
Step 1: convert_to_csv.py → script.csv（30字分割）
    ↓
Step 2: add_furigana.py → script_furigana.csv（フリガナ付き）
    ↓  カラム名変換（Type→type, Speaker→character, Content→text）
Step 3: generate_comicle_csv.py → comicle_output.csv（120ページ目標）
    ↓
Step 4: compare_dialogues.py → 比較分析レポート
    ↓
Step 5: YouTubeメタデータ生成（タイトル3案 + 説明文）
    ↓
Step 6: サムネイル用Geminiプロンプト生成（英語）
    ↓
[成果物] script_furigana.csv + comicle_output.csv + レポート + メタデータ + サムネプロンプト
```

### 部分実行への対応

| リクエスト | 対応 |
|-----------|------|
| 「〇〇をテーマにフル制作」 | Step 0〜6すべて実行 |
| 「台本だけ作って」 | Step 0〜1のみ |
| 「このscript.csvからcomicle CSVを作って」 | Step 2〜4のみ（添付ファイル使用） |
| 「このCSVにフリガナを付けて」 | Step 2のみ |
| 「script.csvとcomicle_output.csvを比較して」 | Step 4のみ |
| 「YouTubeのタイトルと説明文を作って」 | Step 5のみ |
| 「○○のサムネを作って」 | Step 6のみ |

---

## Step 0: 台本Markdownの作成

テーマについてWebリサーチを行い、台本Markdownを作成する。

### 台本フォーマット

```markdown
# タイトル

## 第1章 時代定義

ヨウイチ「セリフ内容」
ミユ「セリフ内容」
pause,,,
```

- セリフは `話者名「セリフ」` 形式（「」括弧で囲む）
- ポーズは `pause,,,` と記述（場面転換箇所に挿入）
- 話者: ミユ（Female_3、質問役）、ヨウイチ（Male_15、解説役）

### 6段階シナリオ構成

| フェーズ | 内容 | 目安行数 |
|---------|------|---------|
| 1. 時代定義 | 時代・人物の基本紹介、結論先出し | 20〜30行 |
| 2. トリガー | 時代構造と変化のきっかけ | 20〜30行 |
| 3. 権力争い | 対立・戦い・出世の過程 | 30〜40行 |
| 4. 思想対立 | 価値観の衝突・致命的事件 | 20〜30行 |
| 5. 結末 | 歴史的転換点・結末 | 20〜30行 |
| 6. エンディング | 遺産・現代への意義・まとめ＋CTA | 15〜25行 |

### セリフ設計ルール

- **推奨**: 15〜25字 / **上限**: 30字（フリガナ除去後）
- **例外**: 和歌・引用文のみ30字超え許容
- **最小**: 3字以上（「？」だけのような断片は禁止）
- 専門用語は初出時に必ず説明を添える
- 数字・年号は1セリフに最大2つまで
- 1分以上ヨウイチが独演しない（ミユの質問・相づちを挟む）
- 第6章の末尾には必ずCTAブロックを組み込むこと（後述「エンディングCTAテンプレート」参照）
- 締めセリフ `ヨウイチ「また次回、別の歴史の物語を一緒に探ろう。」` はCTAブロック内で1回だけ使用し、本編まとめ部分では使わない

### キャラクター設定

- **ミユ（女子大生）**: 視聴者の代弁者。ヨウイチを「教授」と呼ぶ。短い質問と要約が中心。外見は `assets/characters/ミユ.png` 参照
- **ヨウイチ（教授）**: 分かりやすく整理して結論を出す。ミユを「ミユくん」と呼ぶ。外見は `assets/characters/ヨウイチ.png` 参照（眼鏡をかけない）

### エンディングCTAテンプレート

第6章の末尾に以下のCTAブロックを組み込む。本編まとめ → CTA → 締めセリフの順。

**標準版（約9行追加）**

```markdown
ミユ「今回も面白かったです、教授！」
ヨウイチ「楽しんでもらえたなら嬉しいよ。」
pause,,,
ミユ「みなさん、この動画が面白かったら、いいねボタンをポチッとお願いします！」
ミユ「コメント欄で感想や気になる人物も教えてくださいね。」
ヨウイチ「まだチャンネル登録がお済みでない方は、ぜひ登録をお願いします。」
ヨウイチ「みなさんの応援が、次の動画を作る大きな力になります。」
pause,,,
ヨウイチ「また次回、別の歴史の物語を一緒に探ろう。」
ミユ「それではまた！」
ヨウイチ「さようなら。」
```

**短縮版（ページ数が厳しい場合、約4行）**

```markdown
ミユ「いいね、コメント、チャンネル登録、よろしくお願いします！」
ヨウイチ「みなさんの応援が次の動画の力になります。」
pause,,,
ヨウイチ「また次回、別の歴史の物語を一緒に探ろう。」
```

**次回予告あり版（標準版の行7を差し替え）**

```markdown
ヨウイチ「次回は【人物名】の物語をお届けする予定だ。お楽しみに。」
```

CTA設計ルール:
- ミユ＝いいね・コメント担当、ヨウイチ＝チャンネル登録・感謝担当
- CTA部分のセリフはフリガナ不要（日常語のみ）
- CTA追加分は約9行 → 本編セリフ数を130行以内に収めれば合計139行前後で120ページ目標に収まる
- 短縮版を使う場合は本編134行程度まで許容

---

## Step 1: 台本CSV生成

```bash
python3 scripts/convert_to_csv.py script_raw.md output/script.csv
```

- `ミユ「セリフ」` / `ヨウイチ「セリフ」` → dialogue行に変換
- `pause,,,` → pause行に変換
- 句点（。）・感嘆符（！）・疑問符（？）で自動分割
- 30字を超える文は読点（、）で再分割

出力カラム: `No, Type, Content, Speaker, VoiceID, Enabled`

チェックポイント:
- 30字超えセリフが0件であること
- セリフ合計150行前後であること
- CSV形式が正しいこと

---

## Step 2: フリガナ付与

### OpenAI API使用時（推奨）

```bash
export OPENAI_API_KEY="your-key"
python3 scripts/add_furigana.py output/script.csv output/script_furigana.csv
```

GPT-4.1-miniが20行単位のバッチ処理でフリガナを自動付与。完了まで数分。

### API未設定時（ルールベース代替）

```bash
python3 scripts/add_furigana_local.py output/script.csv output/script_furigana.csv
```

辞書ベースでフリガナを付与。精度はGPT版より劣るが同一フォーマットで出力。

### フリガナルール

- 人名・官職名・地名・特殊読みに `漢字（カタカナ）` 形式で付与
- 年号は必須: `1167（センヒャクロクジュウナナ）年`
- 既にフリガナが付いている箇所は変更しない
- 目標: 全セリフ行の40%以上にフリガナが付与されている状態
- ルールベース版だけでは4〜8%程度 → 歴史固有名詞の辞書補完パスが必要

---

## Step 3: Comicle CSV生成

### カラム名変換（必須）

`script_furigana.csv`のカラム名と`generate_comicle_csv.py`が期待するカラム名が異なるため、先に変換する。

```python
import csv

rows = []
with open('output/script_furigana.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append({'type': row['Type'], 'character': row['Speaker'], 'text': row['Content']})

with open('output/script_converted.csv', 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['type', 'character', 'text'])
    writer.writeheader()
    writer.writerows(rows)
```

### Comicle CSV生成

```bash
python3 scripts/generate_comicle_csv.py output/script_converted.csv output/comicle_output.csv 120
```

- 第3引数: 目標ページ数（120推奨、**絶対に120を超えないこと**）
- フリガナはセリフ出力時に自動除去される
- テンプレ1を60〜75%、テンプレ2/4/5で残りを構成

出力カラム: `ページ番号, 使用するコマ割りテンプレ, 漫画作成のプロンプト`

### 【作画】フィールドの後処理（重要）

generate_comicle_csv.pyのデフォルト出力は汎用的な現代アニメ/ビジネス漫画風の【作画】になる。
**必ず後処理で、各ページの対応する物語章に合わせた歴史的に正確なシーン描写に書き換えること。**

書き換え例:
- ❌ `ビジネス漫画向け、清潔感重視、整った線画、現代的でクリアなアニメ調`
- ✅ `平安時代の宮廷、束帯姿の貴族たちが並ぶ紫宺殿の御前、桜の庭園、柔らかい光`

---

## Step 4: 比較分析

### 実行前パッチ（必須）

```bash
sed -i "s/row.get('ストーリー', '')/row.get('漫画作成のプロンプト', row.get('ストーリー', ''))/g" scripts/compare_dialogues.py
```

### 実行

```bash
python3 scripts/compare_dialogues.py output/script_furigana.csv output/comicle_output.csv
```

### 合格基準

| 項目 | 合格基準 |
|------|---------|
| セリフ反映率 | 100%（全件一致） |
| 30字超えセリフ | 0件（和歌・引用文を除く） |
| 感情コードN率 | 98%未満が理想（改善推奨） |
| 2コマページ比率 | 25%以上が目標（改善推奨） |

---

## Step 5: YouTubeメタデータ生成

台本の内容に基づいて以下を生成する。

### タイトル（3案）

3つの異なるアーキタイプで作成:
1. **感情・インパクト訴求**: 感情に訴えるドラマチックな表現
2. **知的好奇心型（Why?フレーム）**: 「なぜ」で始まる問いかけ
3. **コントラスト・ギャップ型**: 栄光と転落の落差を強調

ルール:
- 60代以上の視聴者に馴染みのある表現を使う
- 過度にカジュアルな言葉遣いは避ける
- チャンネル名「知ってたつもり日本史」やシリーズ名を含めてもよい

### 説明文（構造化）

```
動画の要約（2〜3行）

▼ 目次
00:00 導入
XX:XX 第1章のタイトル
XX:XX 第2章のタイトル
...

▼ このチャンネルについて
定型文

#日本史 #歴史 #知ってたつもり日本史 #歴史の敗者シリーズ #【人物名】
```

---

## Step 6: サムネイル用Geminiプロンプト生成

YouTubeサムネイル画像をGeminiで生成するための英語プロンプトを出力する。

### 入力パターン

- **推奨**: 台本CSV（script_furigana.csv等）+ 人物名 + 号数
- **代替**: 人物名のみ（Claudeが史実から推定）

### 画像仕様（固定）

- 比率: 16:9（1280x720px）、YouTubeサムネイル
- スタイル: Semi-realistic digital art（アニメ調ではない）
- 同一人物の「光（左）」と「闇（右）」の2状態を描く

### 画面構成

- 左側（栄光）: ハイキー照明、温かい光、黄金の後光、理想化された背景
- 右側（転落）: ローキー照明、冷たい光、怨霊化（onryō transformation）
  - 髪が翼へ変化、目が赤く光る、血を向く、赤と黒の怨念オーラ
- 中央: 黒帯（black band）に縦書きテキスト

### テキスト配置（固定）

| 位置 | 内容 | スタイル |
|------|------|----------|
| 左上 | 「大人の学び直し」 | 赤背景に白文字（横書き） |
| 右上 | 「歴史の敗者シリーズ ◯」 | 黒枠（横書き） |
| 黒帯・右側上半分 | 人物名 | 金色・黄色、最大フォント、**縦書き** |
| 黒帯・右側下半分 | サブコピー（2行） | 白色、中フォント、**縦書き** |
| 黒帯・左側 | 詳細コピー（15文字×2行） | 白色、中小フォント、**縦書き** |

### 英語プロンプトテンプレート

```
A dramatic YouTube thumbnail (16:9, 1280x720px) in a semi-realistic digital art style. The image is dynamically split diagonally, contrasting "GLORY (left)" and "DOWNFALL (right)" of [PERSON_NAME_EN] — the same person shown in two radically different states.

LEFT SIDE (GLORY):
[LEFT_VISUAL_EN — 衣装、表情、小道具、オーラの詳細を英語で展開]
Aesthetics: High-key lighting, warm golden tones, a radiant golden halo behind the figure, an aura of pure luminous energy. Background: [LEFT_BG_EN].

RIGHT SIDE (DOWNFALL):
[RIGHT_VISUAL_EN — 衣装の損傷、体勢の詳細を英語で展開]
Dramatic vengeful spirit (onryō) transformation: [ONRYO_DETAILS_EN]. Enveloped in a sinister red-and-black grudge aura (NO halo). [GAZE_DIRECTION].
Aesthetics: Low-key lighting, cold desaturated tones, chaos and devastation. Background: [RIGHT_BG_EN].

TEXT OVERLAY (Japanese text):
- Top-left (solid red background box with white text, horizontal): "大人の学び直し"
- Top-right (black bordered box, horizontal): "歴史の敗者シリーズ [NUMBER]"
- A solid black vertical band in the center of the image, between the two figures. Inside the band:
  - Right column, upper half (golden yellow, largest font, VERTICAL writing top-to-bottom): "[PERSON_NAME_JP]"
  - Right column, lower half (white, medium font, VERTICAL writing top-to-bottom, 2 lines):
    - Line 1: "[SUBCOPY_LINE1_JP]"
    - Line 2: "[SUBCOPY_LINE2_JP]"
  - Left column (white, medium-small font, VERTICAL writing top-to-bottom, 2 lines, max 15 characters per line):
    - Line 1: "[DETAIL_LINE1_JP]"
    - Line 2: "[DETAIL_LINE2_JP]"

The person name, sub-copy, and detail copy are all inside the central black band as vertical Japanese text (tategaki). Only the top-left and top-right branding elements are horizontal. All text is crisp and highly legible.
```

サムネ生成時の注意:
- 怨霊化の描写は人物ごとにユニークにする（義経→天狗的な翼、清盛→炎の化身 等）
- テキスト要素の日本語はそのまま出力する（翻訳しない）
- 号数の指定がなければ「◯」のまま残して確認を促す
- 参考例: `references/yoshitsune_thumbnail.md`

---

## 運用上の重要なナレッジ

### ページ数制御

- 120ページが上限（絶対に超えない）
- ~139行のダイアログが120ページに概ね対応する
- ページ数超過時はgenerate_comicle_csv.pyのパラメータではなく、**台本のセリフ行数を減らして対処**
- CTA標準版（9行）を使う場合、本編は130行以内に収める

### フリガナカバレッジ

- ルールベーススクリプト（add_furigana_local.py）だけでは4〜8%程度
- 目標40%達成には、歴史固有名詞（人名、時代名、官職名、合戦名）を対象とした辞書補完パスが必要
- GPT版（add_furigana.py）なら高精度で達成可能

### 【作画】フィールド

- generate_comicle_csv.pyのデフォルトは汎用的な現代アニメ/ビジネス漫画スタイル
- 必ず後処理で、ページ番号範囲ごとに物語章に対応した歴史的シーン描写に書き換える

### YouTubeタイトル

- 3つのアーキタイプ（感情訴求、知的好奇心、コントラスト）で毎回3案
- 60代以上向け: 馴染みのある表現、過度にカジュアルな言い回しは避ける

### 「歴史の敗者」フレーミング

- 何かを成し遂げた後に敗北した人物（「勝ったが最終的に負けた」悲劇のアーク）に最適
- 例: 後醍醐天皇（倒幕に成功→建武の新政の失敗）、崇徳上皇（保元の乱で敗北→怨霊化）

---

## よくある問題と対処

| 問題 | 原因 | 対処 |
|------|------|------|
| セリフ反映率が100%未満 | カラム名の不一致 | Step 3のカラム変換を確認 |
| compare_dialogues.pyでセリフ抽出0件 | `ストーリー`カラム不一致 | `sed`パッチを適用（Step 4参照） |
| フリガナがcomicle CSVに残る | generate_comicle_csv.pyの旧バージョン | フリガナ除去ロジックの有無を確認 |
| 30字超えセリフが多い | 台本のセリフが長すぎる | 読点で分割して台本修正 → Step 1から再実行 |
| add_furigana.pyがエラー | OPENAI_API_KEY未設定 | add_furigana_local.pyで代替 |
| ページ数が120を超える | セリフ行数が多すぎる | 台本を凝縮してセリフ行数を減らす |
