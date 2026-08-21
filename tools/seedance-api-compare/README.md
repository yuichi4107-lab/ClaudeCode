# Seedance 2.0 API 比較テスト (Atlas Cloud vs EvoLink)

同一プロンプトを両プロバイダに投げて、生成時間・品質・安定性を比較するツール。
TopView(手動UI)からClaude Code自動化への移行先を決めるための検証用。

## 事前準備(ユーザー作業)

1. **Atlas Cloud**: <https://www.atlascloud.ai/> でサインアップ → Dashboard → API Keys でキー枚行(無料クレジットあり)
2. **EvoLink**: <https://evolink.ai/> でサインアップ → Get API Key(無料クレジットあり・カード不要)
3. キーを `.env` に設定:

   ```bash
   cd tools/seedance-api-compare
   cp .env.example .env
   # .env を開いて2つのキーを貼り付け
   ```

## 実行

```bash
python3 compare_seedance.py --prompt "A cat walking on a beach at sunset, cinematic" --duration 5 --resolution 720p
```

- 片方だけ試す: `--only atlas` / `--only evolink`
- 結果は `output/` に `<日時>_<プロバイダ>_<解像度>_<秒数>s.mp4` と `<日時>_summary.json` で保存
- キー未設定のプロバイダは自動スキップ

## 料金目安(5秒・720p・1本)

| プロバイダ | std | fast |
|---|---|---|
| Atlas Cloud(全解像度一律) | $0.56 | $0.45 |
| EvoLink(720p) | $1.00 | $0.81 |

失敗した生成は両者とも課金されない(公称)。

## 注意

- モデルIDはプロバイダ側で変わることがある。404/400でモデル名エラーが出たら
  `.env` の `ATLAS_MODEL` / `EVOLINK_MODEL` で上書きする
- 動画URLの有効期限は24時間程度なので、スクリプトが即ダウンロードして保存する
