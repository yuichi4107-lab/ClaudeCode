# MV Factory

指定した曲テーマ・歌詞（または手持ち音源）から、60秒・9:16のショートMVと
3分・16:9のフルMVをワンコマンドで自動生成するパイプライン。

要件定義書: `.company/projects/MV制作/2026-07-07-MV制作パイプライン要件定義書.md`

全自動設計（Telegram承認等の途中承認なし）。ワンコマンドで工程1〜6まで進む。
唯一、工程3（絵コンテ・シーンプロンプト生成）だけはLLM（Claude Code実行時の
エージェント）が作文する設計のため、事前に `storyboard_short.json` /
`storyboard_full.json` を用意しておく必要がある（後述）。

## 前提ツール

- Python 3.9+
- ffmpeg / ffprobe（`brew install ffmpeg`）
- PyYAML（`pip3 install -r requirements.txt`）
- （任意）OpenAI API key: 工程2の歌詞タイムスタンプ解析を精緻化する場合
- Atlas Cloud APIキー: 工程5（動画生成）に必須

## セットアップ

```bash
cd tools/mv-factory
pip3 install -r requirements.txt
cp .env.example .env
# .env を開いて ATLAS_CLOUD_API_KEY を設定
# (tools/seedance-api-compare/.env に既にキーがあれば自動フォールバックするので
#  mv-factory側の.envが空でも動く)
```

## ディレクトリ構成

```
tools/mv-factory/
├── README.md
├── requirements.txt
├── project.yaml.example        # project.yamlのサンプル・全フィールド解説
├── .env.example
├── .env                        # 実キー(gitignore対象)
├── run_pipeline.py             # ワンコマンド実行
├── step1_music.py              # 工程1: 曲生成/投入
├── step2_analyze.py            # 工程2: 曲構成解析
├── step3_storyboard.py         # 工程3: 絵コンテ雛形生成・検証
├── step4_references.py         # 工程4: 参照画像マニフェスト生成
├── step5_generate_clips.py     # 工程5: シーン動画生成(Atlas Cloud)
├── step5b_inspect.py           # 工程5b: クリップ品質ゲート(contact sheet生成)
├── step6_mix.py                # 工程6: 編集・合成(完パケ出力)
├── mvfactory/                  # 共通ロジック(モジュール)
│   ├── common.py                 # .env/project.yaml読み込み、パス解決
│   ├── analysis.py                # 工程2の実装(ffprobe/Whisper/ルールベース)
│   ├── storyboard.py              # 工程3のスキーマ・バリデータ・雛形生成・
│   │                               # character_sheet必須化・スタイル矛盾検出
│   ├── references.py              # 工程4の実装(マニフェスト生成)
│   ├── mix.py                     # 工程6の実装(ffmpeg合成)
│   └── providers/
│       ├── music.py                 # 工程1: Suno API / 手持ち音源 の抽象化
│       └── video.py                 # 工程5: Atlas Cloud呼び出し
└── projects/
    └── {YYYYMMDD}-{曲名スラッグ}/   # 1曲=1プロジェクトディレクトリ
        ├── project.yaml
        ├── input/                    # 手持ち音源投入モード時の元ファイル置き場
        │   ├── song.mp3(or wav)
        │   └── lyrics.txt
        ├── song.mp3(or wav)           # 工程1の出力(共通・1本のみ)
        ├── lyrics.txt
        ├── song_meta.json
        ├── song_structure.json        # 工程2の出力(共通)
        ├── storyboard_short.json      # 工程3-Aの出力(character_sheet含む)
        ├── storyboard_full.json       # 工程3-Bの出力(character_sheet含む)
        ├── references/                # 工程4の出力(60秒版・3分版で共用)
        │   ├── manifest.json
        │   └── *.png
        ├── short/
        │   ├── clips_short/scene_XX.mp4   # 工程5-Aの出力
        │   └── _concat_short.mp4          # 工程6-A中間ファイル
        ├── full/
        │   ├── clips_full/scene_XX.mp4    # 工程5-Bの出力
        │   └── _concat_full.mp4           # 工程6-B中間ファイル
        ├── logs/
        │   ├── clip_audit.json            # 工程5bの検査結果(全シーンok必須)
        │   └── contact_sheets/{short,full}/scene_XX.jpg  # 工程5bの検査用画像
        ├── final_mv_short_9x16.mp4     # 完パケ(60秒・9:16)
        ├── final_mv_full_16x9.mp4      # 完パケ(3分・16:9)
        └── logs/                       # 各工程のログ・JSON結果
```

## project.yaml スキーマ

`project.yaml.example` を `projects/<slug>/project.yaml` としてコピーし編集する。
主なフィールド:

| フィールド | 必須 | 説明 |
|---|---|---|
| `title` | ○ | 曲タイトル(表示用) |
| `slug` | ○ | ディレクトリ名と一致させる(`YYYYMMDD-曲名スラッグ`) |
| `genre` | ○ | ジャンル |
| `vocal` | - | female / male / none / duet |
| `theme` | - | 曲テーマ(Suno APIモード時は必須相当) |
| `song_source` | ○ | `suno_api` または `manual` |
| `suno_api.*` | song_source=suno_apiなら実質必須 | Suno公式API呼び出し用パラメータ(仕様確定待ち) |
| `manual_audio.audio_path` / `lyrics_path` | song_source=manualなら必須 | 手持ち音源・歌詞のプロジェクト相対パス |
| `versions.short` / `versions.full` | ○ | 尺(60/180秒)・アスペクト比(9:16/16:9)・クリップ長 |
| `reference_images.*` | - | 参照画像使用有無・キャラ設定・世界観設定 |
| `video_generation.*` | - | Atlas Cloudのモデル・解像度・リトライ設定 |
| `mix.*` | - | フェード秒数・尺合わせモード |
| `budget.max_usd_per_run` | - | 自己申告の予算目安(厳密な課金停止機能ではない) |

バリデーションは `mvfactory/common.py: validate_project_yaml()` が行う。
必須フィールド欠落・不正な `song_source` / `aspect_ratio` はエラーで停止する。

## 曲生成の3モード（工程1）

### (a) `song_source: suno_api`

Suno公式パートナーAPI呼び出しモード。2026-07-07時点でSuno公式APIの一般公開仕様
（エンドポイント・パラメータ・料金）は非公開（限定パートナーベータのみ）。
本パイプラインは `mvfactory/providers/music.py: SunoApiProvider` として
呼び出し口を抽象化済みだが、実際のHTTP実装は **オーナーがAPIキー・仕様情報を
入手してから追加する** 前提。未設定・未実装のまま実行すると、明確なエラー
メッセージを出して停止する（サイレント失敗を避ける設計）。

### (b) `song_source: suno_bridge`

opensuno Bridge Mode（`.agents/skills/suno-music-gen/`）経由で、**自分のSuno
アカウント**から曲を生成するモード。パートナーAPIキー不要、追加課金なし
（Sunoクレジットのみ消費）。`mvfactory/providers/music.py: SunoBridgeProvider`
が実装している。

仕組み: Claude Code → `localhost:3001`(opensuno bridge) → WebSocket → Chrome拡張
→ suno.comログイン済みタブ → Suno公式内部API。

生成前に必ず `GET /api/status` の `connected` を確認する。`false` の場合は
「suno.comのログイン済みタブを開いてください」とエラーを出して停止する
（サイレントにフォールバックしない）。

呼び出しは bridgeのローカルAPI `POST /api/custom_generate`（歌詞・スタイル・
タイトル指定、内部でSuno実APIの `/api/generate/v2/` にマップされる）→
`GET /api/get?ids=...`（内部で `/api/feed/v2` にマップ）でポーリング
（10秒間隔・最大600秒）→ 完了したクリップのmp3をダウンロード、という流れ
（`.agents/skills/suno-music-gen/scripts/suno_generate.py` のパターンを踏襲。
実装時に `/api/generate/v2/` を直接叩いて404になった教訓から、bridgeの
ローカルAPIパスと内部Suno APIパスを混同しないよう明記する）。

**1回の生成で2トラックが返る（Suno仕様）。** 両方ダウンロードした上で以下の
基準で1本を選択する:
1. `status == complete` かつ `audio_url` があるものだけを候補にする
2. 候補のうち **`metadata.duration`（尺）が長い方** を選択（MVの元素材として
   より多くの区間を使えるため）
3. 尺が同じ/取得できない場合は先にcompleteになった方（クリップリスト順）

選ばれなかった方は `alt_song_1.mp3` として保存し、`song_meta.json` に
`alternate_files` / `alternate_ids` / `selection_reason` を記録する。

project.yamlの `suno_bridge.*` フィールド（`title` / `theme` / `lyrics` or
`lyrics_file` / `style_tags` / `instrumental` / `model`）で歌詞・スタイル・
モデルを指定する（`project.yaml.example` 参照）。

### (c) `song_source: manual`

手持ちの音源ファイル（mp3/wav）＋歌詞テキストファイルを
`manual_audio.audio_path` / `manual_audio.lyrics_path` で指定するだけで、
以降の工程がすべて同じ形式（`song.mp3` + `lyrics.txt` + `song_meta.json`）で
動く。Suno APIキー未着の間はこのモードでパイプライン全体の疎通確認ができる。

著作権・商用利用リスク: 手持ち音源の商用利用可否は音源取得元のライセンスに
依存し、本パイプラインはこれを検証・保証しない。Suno生成楽曲を使う場合は
Suno社のサービス利用規約・商用利用条件を確認し、収益化・公開前提のMVに
使う際はオーナーの明示承認を得ること（要件定義書 6章参照）。

## 工程2: 曲構成解析

`song.mp3`（または wav）と `lyrics.txt` から `song_structure.json` を生成する。

- 尺: `ffprobe` で取得
- セクション区切り: `OPENAI_API_KEY` があれば Whisper API のワードタイムスタンプ
  から推定、なければ歌詞の空行区切り＋均等分割のルールベースにフォールバック
- BPM: 現状は固定デフォルト（120）＋ `bpm_confidence: "low"| で明示。精密な
  BPM解析（librosa等）は依存重量化を避けるため未実装。必要なら
  `song_structure.json` を手動編集して上書きできる（`manual_correction_hint`
  フィールド参照）

## 工程3: 絵コンテ・シーンプロンプト生成（LLM生成、人間/エージェントの役割）

このスキームだけは自動化せず、**Claude Codeのエージェントが
`song_structure.json` と `project.yaml` を読んで作文する**設計。

手順:

```bash
# 1. 雛形を書き出す(scenes: [] の空配列)
python3 step3_storyboard.py --project projects/<slug> --version short --mode scaffold
python3 step3_storyboard.py --project projects/<slug> --version full  --mode scaffold

# 2. エージェント(または人間)が storyboard_short.json / storyboard_full.json の
#    scenes[] を編集する。各シーンは以下のフィールドを持つ:
#      scene_id (一意), section (song_structureのsection名と対応), 
#      duration_sec (4〜15の整数、Seedance制約), 
#      video_prompt (カメラワーク・画角・雰囲気を含む英語推奨プロンプト),
#      reference_image_role (none | first_frame | first_last_frame)

# 3. スキーマ・尺整合を検証する
python3 step3_storyboard.py --project projects/<slug> --version short --mode validate
python3 step3_storyboard.py --project projects/<slug> --version full  --mode validate
```

- 60秒版: 曲のサビ・イントロ等からハイライト区間を抽出し、合計尺が
  `target_duration_sec`（60秒）に近くなるようシーンを組む（許容差±5秒）
- 3分版: 曲全体をカバーするようシーン分割する（許容差±15秒、工程6で
  trim/freeze-frameにより最終的に曲尺へ厳密一致させる）
- 各シーンの尺は4〜15秒（Seedance 2.0の制約）
- `characters` / `world` は `reference_images` の設定を引き継ぎ、60秒版・
  3分版で同一のキャラ・世界観設定を共有する

`run_pipeline.py` はstoryboardが無い場合、雛形を書き出した上でそのバージョン
の処理を中断し、次に何をすべきかをログに明示する（全自動だが、LLM作文工程
だけは人間/エージェントの介在を要求する設計）。

### キャラクターシート必須化（2026-07-07 品質ゲート、オーナー指摘対応）

パイロットMVで「シーンごとに服装・髪型が変わる」問題が発覚したため、
`storyboard_{short,full}.json` に **`character_sheet`（top-levelまたは
`characters[].character_sheet`）を必須化**した。

```json
{
  "character_sheet": {
    "hairstyle": "shoulder-length black hair with soft bangs",
    "outfit": "white long-sleeve shirt tucked into light blue denim jeans, small beige backpack",
    "shoes": "white canvas sneakers, one shoe per foot",
    "build": "slim build, young adult Japanese woman, approx. 165cm"
  },
  "scenes": [ ... ]
}
```

`mvfactory/storyboard.py: validate_storyboard()` は以下を機械チェックする:

- `character_sheet` に `hairstyle` / `outfit` / `shoes` / `build` の4キーが
  揃っているか（欠けていれば検証エラー）
- 各シーンの `video_prompt` が `character_sheet` の記述語をどれだけ
  含んでいるか（ゆるいトークン一致判定、一致率25%未満で検証エラー）。
  人物が映らないシーン（風景のみ等）は `scene.features_character: false`
  を明示すればこのチェックをスキップできる

### スタイル矛盾バリデータ（同上）

`video_prompt` に矛盾するスタイル語（アニメ調×実写風、3DCGアニメ×実写風等）
が同一プロンプト内に混在していたら検証エラーにする。パイロットMVで
"Japanese anime-style live-action-look" という自己矛盾語が全シーンに
混入し、アニメ/実写混在の原因になった教訓を反映。スタイルは単一方向に
統一し、逆方向のスタイル語は `NOT anime, NOT cel-shaded, NOT 3D animation,
NOT CGI render` のように明示的に否定すること。

## 工程4: 参照画像生成（任意、60秒版・3分版で共用）

`step4_references.py` は `reference_images.enabled` に応じて
`references/manifest.json` を書き出す。実際の画像生成は既存スキルに委譲する:

- `nanobanana2-image-gen` スキル（Google AI Studio API、コード呼び出し可）
- `openai-image-gen` スキル（ChatGPT Pro Web経由、API不使用のガードレール品）

エージェントは `references/manifest.json` の `images[]`（role/prompt/
output_file）を見て、`references/*.png` を生成・保存する。
`references/` に既にPNGがあれば工程4は再生成をスキップする（60秒版・3分版の
重複生成回避）。`reference_images.enabled: false` の場合はtext-to-videoの
みで工程5に進む。

## 工程5: シーン動画生成（Atlas Cloud Seedance 2.0）

- エンドポイント: `POST https://api.atlascloud.ai/api/v1/model/generateVideo`
  → `GET .../prediction/{id}`（非同期ポーリング、15秒間隔・30分タイムアウト）
- モデル: `bytedance/seedance-2.0/text-to-video`（`project.yaml` の
  `video_generation.model` または環境変数 `ATLAS_MODEL` で上書き可能）
- **User-Agentヘッダー必須**: CloudflareがPython標準UAを403で弾くため、
  `mvfactory/providers/video.py` は全リクエストに `User-Agent: mv-factory/0.1`
  を付与する（`tools/seedance-api-compare/compare_seedance.py` の実績パターン
  を踏襲）
- image-to-video: `reference_image_role` が `first_frame` / `first_last_frame`
  の場合、`references/*.png` をbase64 data URIに変換して `images` パラメータ
  として渡す
- 動画URLの有効期限: 生成完了検知後、即座にダウンロードして
  `{short,full}/clips_{short,full}/scene_XX.mp4` に保存する（URLを保持し続けない）
- 残高枯渇検知: HTTP 402/403かつレスポンスに `insufficient` / `balance` /
  `payment required` 等の文言が含まれる場合、`BalanceExhaustedError` として
  即座に全体を中断し、明確なエラーメッセージを出す
- リトライ/スキップ方釽: `max_retries`（デフォルト2）回リトライし、それでも
  失敗したシーンは `skipped` としてログに記録し、他のシーン生成は継続する
  （1シーン失敗で全体を止めない。ただし残高枯渇は例外で即中断）
- 想定クリップ数・コスト目安（`$0.112/秒` 実務目安、要件定義書5章参照）:
  - 60秒版: 約8〜12クリップ（5秒×12本で概算$6.7）
  - 3分版: 約20〜40クリップ（5秒×36本で概算$20.2）

```bash
# dry-run(API呼び出しなし、プロンプト確認のみ)
python3 step5_generate_clips.py --project projects/<slug> --version short --dry-run

# 実行
python3 step5_generate_clips.py --project projects/<slug> --version short
```

## 工程5b: クリップ品質ゲート（2026-07-07新設、オーナー指摘対応）

工程5（クリップ生成）完了後・工程6（合成）前に**必ず**通す検査ゲート。
`run_pipeline.py` はこのゲートを自動で挟み、`logs/clip_audit.json` で
全シーンが `"ok"` と記録されるまで工程6に進まない（旧 style_audit の
仕組みはこのゲートに統合済み）。

### 検査観点チェックリスト

1. **画風統一**: アニメ調・3DCGアニメ調・実写風が混在していないか
   （storyboard側のスタイル矛盾は工程3のvalidateで機械チェック済みだが、
   実際の生成結果がプロンプト指示通りになっているとは限らないため
   目視必須。パイロットMVでは"NOT cel-shaded, NOT cartoon"だけでは
   3DCGアニメ調の生成を防げず、"NOT 3D animation, NOT CGI render,
   NOT Pixar-style"を追加してようやく解消した実績あり）
2. **人物・服装・髪型の一致**: `character_sheet` の記述（髪型・服装・靴・
   体型）がクリップ内、およびクリップ間で一貫しているか
3. **物理破綻**（オーナー指摘の具体例）:
   - 靴・手足の破綻: 片足に2つの靴が見える／靴を履いていない／
     指や手足の数がおかしい
   - 移動方向の矛盾: 自転車を漕いでいるのに前進しない、背景が流れる
     向きと進行方向が逆、後退しているように見える
   - 昇降装置の方向矛盾: エスカレーター/エレベーターの移動方向と
     人物の向き・体動が矛盾している

### 使い方・運用フロー

```bash
# contact sheet生成(1クリップにつき時系列5フレームを横に並べた1枚画像)
python3 step5b_inspect.py --project projects/<slug> --version short

# 特定シーンのみ(再生成後の再検査等)
python3 step5b_inspect.py --project projects/<slug> --version short --scene scene_03
```

1. `step5b_inspect.py` が `logs/contact_sheets/{version}/{scene_id}.jpg`
   （時系列で等間隔抽出した最低5枚のフレームを1行に並べたcontact sheet）
   を生成し、`logs/clip_audit.json` に `"pending_review"` の雛形を書き込む
2. **エージェントがcontact sheet画像をReadし、上記チェックリストで目視判定**
   する（このスクリプト自体は自動判定しない。フレームの時系列並びから
   動きの方向・昇降装置との整合を判定できるようにしている）
3. 判定結果を `logs/clip_audit.json` の該当シーンに記録する:
   ```json
   {
     "version": "short",
     "scenes": {
       "scene_03": {
         "status": "ok",
         "style": "live-action",
         "character_consistency": "ok",
         "physical_issues": [],
         "notes": "",
         "reviewed_by": "quality-gate-agent",
         "reviewed_at": "2026-07-07T12:00:00"
       }
     },
     "all_reviewed": true,
     "all_ok": true
   }
   ```
   `status` は `"ok"` または `"ng"`（`physical_issues` に理由を記載）
4. NGクリップは `backup/` へ退避し、`character_sheet` 相当の固定記述と
   物理破綻対策のポジティブ/ネガティブ表現（例: `"wearing white sneakers
   on both feet, one shoe per foot"`, `"bicycle moving forward, background
   streaming backward naturally"`, `"escalator moving upward, person facing
   forward in the direction of travel"`）をプロンプトに反映して再生成する
5. 再生成分だけ `step5b_inspect.py --scene <id>` で再度contact sheet生成→
   目視→`clip_audit.json`更新、を繰り返す
6. 全シーンが `"ok"` になったら工程6（合成）に進む

`run_pipeline.py` は工程5の直後に `step5b_inspect.py` を自動実行して
contact sheetを生成するが、目視判定はエージェント（人間の介在を要求する
設計）が行う必要があるため、`logs/clip_audit.json` で全シーン `"ok"` が
確認できない場合は工程6に進まず停止し、次のアクションをログに表示する。

## 工程6: 編集・合成（完パケ出力）

`mvfactory/mix.py` がffmpegで以下を行う:

1. 各クリップを対象アスペクト比（9:16: 1080x1920 / 16:9: 1920x1080）に
   `scale + pad` で正規化し、H.264/AACに統一してから `concat demuxer` で結合
2. 曲（`song.mp3`/`wav`）をmux（`-map` で映像はconcat結果、音声は曲を使用）
3. 尺合わせ: **曲の尺を基準（trim_to_music）**とする
   - クリップ合計 < 曲尺 → 最終フレームを `tpad` でfreeze-frame延長
   - クリップ合計 > 曲尺 → `-t` で曲尺にtrim
4. フェード: 音声は `afade` でイン/アウト、映像は `fade` でアウトのみ
5. 出力: `final_mv_short_9x16.mp4`（60秒・9:16・H.264/AAC）、
   `final_mv_full_16x9.mp4`（3分・16:9・H.264/AAC）

**short版の曲トリム（重要・2026-07-07パイロットで発覚した不具合の修正）**:
short版は「同じ曲のハイライト区間だけを60秒のクリップに合わせる」設計のため、
`step6_mix.py: resolve_audio_for_version()` が曲尺と `target_duration_sec`
（60秒）を比較し、曲の方が長い場合は**曲の先頭からtarget_duration_sec秒だけ
切り出した一時ファイル**（`_audio_trimmed_short.mp3`）を作ってからmuxする。
これを行わないと、60秒分のクリップに対して曲全体（3分超）がmuxされ、
`mux_with_music()`が曲尺を基準に映像を引き伸ばしてしまい、実質的に
「静止画に近い状態が延々続く動画」になってしまう（初回パイロットで
`final_mv_short_9x16.mp4` が161秒になる不具合として発覚、修正済み）。
full版は曲全体をそのまま使う（トリムしない）。

既存の `short-video-editor` スキルとの関係: あちらはトーク動画のジェット
カット・テロップ・Whisper前提の編集パイプラインであり、「曲に映像を同期
させる」MV用途とは要件が異なるため直接流用しない。ただし品質検証の考え方
（black frame検知・つなぎ目異音検知）は `video-quality-checker` エージェント
に委任する形で踏襲できる（完パケ後、任意でこのエージェントに検証させることを
推奨。今回のスコープでは自動組み込みはしていない）。

```bash
python3 step6_mix.py --project projects/<slug> --version short
python3 step6_mix.py --project projects/<slug> --version full
```

## ワンコマンド実行

```bash
python3 run_pipeline.py --project projects/<slug>
```

実行順序: 工程1→2（共通・1回のみ）→ 60秒版（工程3-A→4→5-A→5b-A→6-A）→
3分版（工程3-B→4→5-B→5b-B→6-B）。オプション:

- `--only short` / `--only full`: 片方のバージョンのみ実行
- `--dry-run-video`: 工程5をAPI呼び出しせず疎通確認のみ（課金なし）
- `--skip-music`: 工程1をスキップ（既に `song.mp3`/`wav` がある場合）

storyboardが未準備のバージョンがあれば、そのバージョンだけ雛形を書き出して
停止し、次のアクション（エージェントによるscenes作文→validate→再実行）を
ログに表示する。全自動の原則（途中承認なし）は維持しつつ、LLM作文工程だけは
ファイルとして事前に用意されている必要がある設計。

**工程5b（品質ゲート）でも同様に停止する**: 工程5完了後、`run_pipeline.py`
は自動でcontact sheetを生成するが、`logs/clip_audit.json` で全シーンが
`"ok"` と記録されるまで工程6（合成）には進まない。目視判定はエージェントの
介在を要求する設計のため、判定→記録が完了してから再実行するか、
`step6_mix.py` を直接実行する。

## コスト試算

要件定義書5章参照。目安:

- 60秒・9:16版: 動画生成 約$6.7 + 参照画像 約$1〜2 + 曲生成(Suno、未確定)
- 3分・16:9版: 動画生成 約$20.2（曲・参照画像は共用のため追加コストなし）
- セット合計: 約$28〜29 + Suno API利用料（未確定）

Atlas Cloudは要チャージ・カード登録前提で無料クレジットがない。
`project.yaml` の `budget.max_usd_per_run` は自己申告の目安であり、
厳密な課金停止機能ではない（実際の請求はAtlas Cloud管理画面で確認）。

## リスク・残論点

要件定義書 6章・7章を参照。特に:

- Suno楽曲の著作権・商用利用リスクは残論点（Suno公式利用規約確認が必要）
- Suno公式API仕様確定後、`mvfactory/providers/music.py: SunoApiProvider`
  の実HTTP実装が必要
- キャラクター一貫性はクリップ内（image-to-video）では担保できるが、
  クリップ間は同一参照画像の使い回し＋プロンプト設計に依存し完全な保証ではない
- 全自動ゆえ、完パケ後の事後確認（サムネイル一覧、`video-quality-checker`
  エージェントでの検証等）を推奨

## 将来の拡張（今回のスコープ外）

- Telegram経由の事後確認（サムネイル一覧送付等、軽量な仕組み）
- `post-sns` スキルとの自動連携（生成後すぐSNS投稿）
- リップシンク・歌唱アバター生成（Wan 2.6等）
- EvoLinkへのフォールバック（`tools/seedance-api-compare/` に実装資産あり）
