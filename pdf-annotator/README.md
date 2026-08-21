# PDF書き込みツール（pdf-annotator）

日本語で書き込みができるAdobe Acrobat風PDF書き込みツール。ビルド工程なしの静的Webアプリで、Google Drive上のフォルダに置いたまま動作する。

## 現在の実装状況

- **工程1（骨格）**: 完了。vendorライブラリ同梱、PDF表示（ページ送り・ページジャンプ・ズーム）が動作する。
- **工程2（書き込みUI）**: 完了。テキスト・ペン・蛍光ペンの書き込み、undo、ページ毎の保持、ズーム追従が動作する。
- **工程3（保存・日本語フォント埋め込み）**: 完了。「保存」ボタンでpdf-lib+fontkitによる日本語フォント埋め込み・コンテンツストリーム直接描画方式のPDFダウンロードが動作する。

## 起動方法

```
cd pdf-annotator
python -m http.server 8000
```

ブラウザで `http://localhost:8000` を開く。

対象ブラウザ: Chrome（Windows/Mac）。npm/node_modules/ビルドコマンドは一切不要。

## 使い方（工程2時点）

1. 「ファイルを開く」ボタン、またはPDFファイルのドラッグ＆ドロップでPDFを読み込む
2. 「◀ 前へ」「次へ ▶」またはページ番号入力でページを移動、「－」「＋」でズーム
3. ツールバーの「テキスト」「ペン」「蛍光ペン」「選択」でモードを切替（選択中のツールはハイライト表示される）
   - **テキスト**: PDF上をクリックするとその位置に入力ボックスが出現し、日本語（IME）で入力できる。オプション欄でサイズ・色を変更可能
   - **ペン**: マウス/タッチでなぞって自由描画。色・太さはオプション欄で変更可能
   - **蛍光ペン**: 半透明（乗算合成）の太い線で、下の文字が透けて見える
   - **選択**: 既存のテキストをクリックして選択（もう一度クリックで編集モード）、ドラッグで移動、Deleteキーまたは×ボタンで削除。選択中はオプション欄からサイズ・色を変更できる
4. 「元に戻す」ボタンまたは Ctrl+Z（Mac: Cmd+Z）で直前の書き込み操作（追加・編集・移動・削除）を1手ずつ取り消せる
5. ページを切り替えても各ページの書き込みは内部モデルに保持され、戻ると再表示される
6. 「保存」ボタンでPDFに書き込みを焼き込み、`annotated_元ファイル名>.pdf` としてダウンロードする（工程3）
   - 保存中はボタンが「保存中…」表示になり無効化される
   - 保存に失敗した場合は日本語のアラートとステータスバーにエラーが表示される（コンソールにも詳細を出力）

### 既矷のUI上の制限（工程2由来・本工程のスコープ外�）

- テキストツールでPDF背景を1回クリックしてテキストボックスを新規作成した直後は、ブラウザの既定のフォーカス制御により入力欄へフォーカスが移らないことがある（`els.annotationLayer` のmousedownハンドラが `preventDefault()` を呼んでいないため）。この場合はもう一度同じ位置（作成されたテキストボックス自体）をクリックしてから入力すると正しく編集できる。次回の改修候補として記録する。

### 内部モデル（工程3への引き継ぎ）

書き込み内容は描画とは分離した `window.annotationModel` に保持される。

```js
window.annotationModel = {
  [pageNo]: [
    { id, type: "text", x, y, size, color, text },
    { id, type: "ink" | "highlight", color, width, points: [[x, y], ...] },
  ],
};
```

- 座標系: `page.getViewport({ scale: 1.0 })` と同じ座標系（原点は左上、Yは下方向に増加）。ズーム倍率は描画時にのみ乗算し、モデル自体はズームに依存しない。
- PDF標準（左下原点・Y上方向）への変換は `pdfY = pageHeightPt - modelY` として行う（`modelToContentPoint()`、無回転ページで実機検証済み）。
- フォントサイズ・線幅も同じスケール（pt相当）で保存されている。

## 工程3: 保存の実装詳細

### 方式

- 元PDFのバイト列（`state.originalPdfBytes`。読み込み時にpdf.js渡し用とは別に複製して保持）を `PDFLib.PDFDocument.load()` で読み込み、`registerFontkit(fontkit)` した上で `vendor/fonts/NotoSansCJKjp-Regular.otf` を `embedFont(bytes, { subset: true })` でサブセット埋め込みする。
- 全ページの `window.annotationModel` を走査し、テキストは `page.drawText()`（複数行対応、CSSの `line-height:1.3` とフォントのascent/descentからベースライン位置を計算し画面表示とのズレを抑制）、ペン・蛍光ペンは `page.drawSvgPath()`（複数点、画面と同じ二次ベジェ平滑化）または単点の場合は `page.drawCircle()` で、**注釈ではなくページのコンテンツストリームへ直接**描画する。
- 蛍光ペンは `blendMode: PDFLib.BlendMode.Multiply` + `borderOpacity: 0.5` で、画面のmultiply合成+alpha0.55相当の半透明表現を再現する。
- 書き込みのないページはループ内で完全にスキップし、元のページ内容に一切手を加えない。
- 保存は `annotated_<元ファイル名>.pdf` としてダウンロードする。

### フォント埋め込み方式・subset可否について（重要な調査結果）

工程1でREADMEに記載していた `@pdf-lib/fontkit`（vendor/fontkit.umd.min.js）は、**NotoSansCJKjp-Regular.otf のような大規模CID-keyed CFF（CJK OpenType）フォントを `subset:true` でサブセット埋め込みすると、生成されるフォントプログラムが破損する既知の未修正バグ**を持つことが実機検証で判明した（[Hopding/pdf-lib Issue #1232](https://github.com/Hopding/pdf-lib/issues/1232)）。

- 症状: pdf-lib側は例外を投げずに埋め込みに「成功」するが、生成されたPDFをPyMuPDF（FreeTypeベース）で開くと `FT_New_Memory_Face: unknown file format` エラーとなり、テキストが一切描画されない（当初はこの状態で本ツール自身のpdf.jsビューアやChrome内蔵ビューアの目視だけでは気づきにくかったため、独立したレンダラーでの検証が必須だった）。
- 対応: Issue #1232で複数人が報告・確認しているコミュニティ修正版 [`pdf-fontkit`](https://www.npmjs.com/package/pdf-fontkit)（`@pdf-lib/fontkit` からのフォーク、MITライセンス、同じUMDグローバル `fontkit` を公開）に **`vendor/fontkit.umd.min.js` を差し替え**、`subset:true` でも正しく動作することをNode.js単体テストおよびPyMuPDFでの独立レンダリングで確認した。
- 実行時のフォールバック: `pdfDoc.embedFont(bytes, { subset: true })` が例外を投げた場合は `subset:false`（フルフォント埋め込み）にフォールバックする（`app.js` の `buildAnnotatedPdfBytes()`）。採用した方式はコンソールに `[pdf-annotator] 日本語フォント埋め込み方式: subset:true` のようにログ出力される。
- サブセットなし（フルフォント）で埋め込んだ場合、NotoSansCJKjp-Regular.otf自体が約16.4MBあるため、保存後PDFが十数MBに肥大する点に注意（`vendor/fontkit.umd.min.js` を差し替え済みの現状は通常サブセット化が成功し、保存後PDFは元PDF+数十〜百数十KB程度に収まる）。

### 既知の制限

- **回転ページ（`/Rotate` 90/180/270）**: `modelToContentPoint()` にpdf.jsのviewport回転式に基づく座標変換ロジックを実装しているが、**実機検証は無回転（`/Rotate 0`）のPDFのみ**で行っている。回転ページでの位置・文字向きの正確性は未検証であり、ズレる可能性がある。
- ペン/蛍光ペンのストローク描画では `page.drawSvgPath()` が内部で独自にY軸反転（`1 0 0 -1 0 0 cm`）を適用するため、`modelToContentPoint()` の結果をそのまま渡すと二重反転でページ外に描画される不具合が実装中に見つかり、`negateYForSvgPath()` で打ち消して修正済み（`page.drawCircle()` にはこの反転がないため単点ストロークでは適用しない）。

## フォルダ構成

```
pdf-annotator/
├── index.html          アプリ本体（UIシェル）
├── app.js               表示ロジック（pdf.js制御・ページ送り・ズーム）
├── style.css             スタイル
├── vendor/               ローカル同梱ライブラリ・フォント（CDN依存ゼロ）
│   ├── pdf.min.js                 pdf.js 本体 (v3.11.174)
│   ├── pdf.worker.min.js          pdf.js Worker
│   ├── cmaps/                     日本語等CJK PDF描画に必要なCMapリソース
│   ├── standard_fonts/            非埋め込みフォント用の標準フォントリソース
│   ├── pdf-lib.min.js             PDF生成・編集ライブラリ (v1.17.1、工程3で使用)
│   ├── fontkit.umd.min.js         フォント埋め込み用 (pdf-fontkit v1.8.9、工程3で使用)
│   └── fonts/
│       └── NotoSansCJKjp-Regular.otf   日本語フォント（工程3で使用、SIL Open Font License）
└── test/
    ├── sample.pdf              動作確認用の複数ページ日本語PDF
    └── annotated_sample.pdf    工程3の保存機能で実際に生成した検証済み成果物（QA再検証用）
```

## ライブラリ・フォントのバージョンと出典

| ファイル | バージョン | 取得元 |
|---|---|---|
| pdf.min.js / pdf.worker.min.js | v3.11.174 | cdnjs (pdf.js) |
| cmaps/ | pdfjs-dist v3.11.174 | unpkg (pdfjs-dist) |
| standard_fonts/ | pdfjs-dist v3.11.174 | unpkg (pdfjs-dist) |
| pdf-lib.min.js | v1.17.1 | unpkg (pdf-lib) |
| fontkit.umd.min.js | v1.8.9 | unpkg (**pdf-fontkit**、`@pdf-lib/fontkit`のCJK CFFサブセット破損バグ修正フォーク。工程3で差し替え。詳細は上記「フォント埋め込み方式・subset可否について」参照） |
| NotoSansCJKjp-Regular.otf | Noto CJK | GitHub googlefonts/noto-cjk（SIL Open Font License、同梱・再配布可） |

いずれもダウンロード後はローカルファイルとして同梱されており、実行時にCDNへ通信することはない。

## 注意事項

- pdf.js組み込みのFreeText注釈エディタはCJK文字でAppearance Stream生成に既知バグ（Issue #20117）があるため使用しない。pdf.jsは表示専用に限定し、書き込みはCanvas/DOMオーバーレイの自前実装、保存はpdf-lib+fontkitのコンテンツストリーム直接描画方式で実装済み（工程2・3）。
- 対象ブラウザはChrome（Windows/Mac）のみ。他ブラウザでの動作確認・対応は対象外。
- 回転ページ（`/Rotate`≠0）は座標変換ロジックは実装済みだが実機未検証（詳細は「工程3: 保存の実装詳細」参照）。
