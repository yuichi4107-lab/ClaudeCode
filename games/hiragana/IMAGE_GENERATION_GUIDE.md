# 画像生成・組み込み 引き継ぎ書（Higgsfield → ゲーム埋め込み）

> このファイルは、Claude **デスクトップアプリ**で作業を続けるための手順書です。
> Web版セッションでは Higgsfield の `generate_image` が「承認が必要」で実行できなかったため、
> 承認ダイアログが出せるデスクトップ版で続行します。

## ゴール
ひらがなゲームの各お題に **実写画像** を組み込む。組み込み先は2つ：
1. **1ファイル版 `games/hiragana/hiragana-standalone.html`**（ユーザーが実際に使用）→ 画像は **base64 data URI** で `ITEMS[].image` に埋め込み（オフラインのまま動く）。
2. **分割版 `games/hiragana/js/data.js`** → 画像ファイルを `games/hiragana/assets/images/<name>.png` に保存し、`image` にそのパスを設定。

`renderPicture()` は `item.image` があれば `<img>`、無ければ絵文字を表示する作りなので、**`image` を入れるだけで反映**される（コード変更不要）。

## 進め方（推奨：まず4枚 → 確認 → 残り）
1. **生成**：`mcp__…__generate_image` を使用。承認ダイアログが出たら「許可」。
   - model: `nano_banana_pro`
   - aspect_ratio: `1:1`
   - count: 1
   - prompt: 下表の「被写体」を、共通テンプレートに当てはめる
   - 共通テンプレート（英語推奨）:
     `A <被写体>, full subject clearly visible and centered, photorealistic, plain solid white background, soft even studio lighting, cute and clean, no text, no watermark`
2. **取得**：結果の画像URL/`job_id` を取得（必要なら `show_generations` / `job_display`）。
3. **ダウンロード→縮小→base64**：
   - 画像をダウンロードし、**一辺 300px 程度**へ縮小（PIL/ImageMagick 等）。例：
     ```bash
     # 例（要 ImageMagick）。<in> をダウンロード画像、<name> を下表のファイル名に
     convert <in> -resize 320x320 -background white -gravity center -extent 320x320 games/hiragana/assets/images/<name>.png
     # base64 data URI を作る
     printf 'data:image/png;base64,' > /tmp/<name>.txt
     base64 -w0 games/hiragana/assets/images/<name>.png >> /tmp/<name>.txt
     ```
   - ※26枚を base64 で `hiragana-standalone.html` に全部入れると数MBになる。**各画像を縮小**してサイズを抑える。
4. **埋め込み**：
   - `hiragana-standalone.html` の対象 `ITEMS` 行の `image` に `data:image/png;base64,....` を設定（`say` 等は残す）。
   - `js/data.js` の対象 `image: null` を `'assets/images/<name>.png'` に変更。
5. **検証**：`python -m http.server` で配信し Playwright で対象語が `<img>` 表示・出題/正解の進行・JSエラー無しを確認。`file://` 相当でも画像が出ること（base64時）。
6. **コミット＆プッシュ**：ブランチ `claude/hiragana-learning-game-km4xpy`。更新版 `hiragana-standalone.html` をユーザーへ送付。OKなら残りへ展開。

## まず作る4枚（テスト用）
| ファイル名 | 被写体（prompt の <被写体>） |
|---|---|
| shoubousha | bright red Japanese fire truck |
| shovelcar | yellow hydraulic excavator (power shovel) construction vehicle |
| inu | cute friendly Shiba Inu puppy, sitting, facing camera |
| usagi | cute fluffy white rabbit, sitting, facing camera |

## 全26語（ファイル名 ↔ 被写体）
### はたらく くるま
| ファイル名 | 被写体 |
|---|---|
| shoubousha | bright red Japanese fire truck |
| trailer | large articulated semi-truck with trailer |
| shovelcar | yellow hydraulic excavator (power shovel) |
| dumpcar | yellow dump truck |
| kuruma | a friendly compact family car |
| densha | a commuter passenger train |
| bus | a city route bus |
| hikouki | a passenger airplane |
| fune | a ship / boat on plain background |
| taxi | a taxi cab |
| patocar | a police patrol car |
| rocket | a space rocket |

### どうぶつ
| ファイル名 | 被写体 |
|---|---|
| inu | cute Shiba Inu puppy, sitting, facing camera |
| neko | cute kitten, sitting, facing camera |
| kirin | a giraffe, full body |
| lion | a friendly lion, full body |
| usagi | cute fluffy white rabbit, sitting |
| zou | an elephant, full body |
| saru | a cute monkey, full body |
| panda | a giant panda, full body |
| uma | a horse, full body |
| buta | a pink pig, full body |
| kame | a turtle |
| tori | a small cute bird |
| kuma | a friendly brown bear, full body |
| penguin | a penguin, full body |

## 注意
- `answer`（さいしょの文字）・読み上げ仕様（`say`）は画像化しても変更しない。
- 全部そろわなくてOK。`image` を設定した語だけ画像、残りは絵文字。
- 生成はクレジット消費。まず4枚で品質・サイズ・組み込みを確認してから残りへ。
