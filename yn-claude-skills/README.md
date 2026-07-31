# yn-claude-skills

YN Factory の全社共通 Claude Code スキル・エージェントを、プラグインとして全リポジトリから使えるようにするマーケットプレイスです。

これまで各リポジトリの `.claude/skills` に置いていたスキルをここに集約しました。プラグインとしてインストールすれば、**どのリポジトリで作業していても同じスキルが使えます**。

## インストール

```bash
# マーケットプレイスを登録（初回のみ）
/plugin marketplace add yuichi4107-lab/yn-claude-skills

# 必要なプラグインだけ入れる
/plugin install yn-company@yn-factory
/plugin install yn-publishing@yn-factory
```

更新は `/plugin marketplace update yn-factory` で反映されます。

## 収録プラグイン

| プラグイン | 内容 | スキル | エージェント |
|---|---|---|---|
| `yn-company` | 会社運営。秘書・CEO振り分け、品質ループ（要件定義→実行→品質チェック）、営業ブリーフィング、週次レビュー、セッション引き継ぎ | 4 | 3 |
| `yn-publishing` | 電子書籍出版。テーマ調査→原稿執筆→マンガ化→KDP表紙・メタデータ生成 | 6 | — |
| `yn-media` | 動画・音楽制作。ショート動画編集、shorts-factory 運用、Instagramリール、Suno楽曲生成 | 4 | 3 |
| `yn-sns` | SNS運用。note記事の企画・執筆・投稿（5アカウント週次バッチ）、X/Instagram/Facebook/Threads投稿 | 3 | 6 |
| `yn-imagegen` | 画像生成。ChatGPT Images 2.0 ガードレール、Codexキュー処理、NanoBanana2 (Gemini) API生成 | 3 | — |

分割してあるのは、使わない領域のスキル説明でコンテキストを消費しないためです。動画を扱わないPCでは `yn-media` を入れない、といった運用ができます。

## 実行環境の前提

一部のスキルはローカル環境に依存します。クラウド実行環境（Claude Code on the web など）では動きません。

- `suno-music-gen` — Mac の `~/tools/opensuno` 常駐と Chrome拡張、suno.com ログイン済みタブ
- `openai-image-gen` / `codeximage` — ChatGPT Pro Web のブラウザ操作
- `shorts-factory-ops` — shorts-factory の LaunchAgent と Telegram Bot
- `handoff` — `.company/secretary/HANDOFF.md` の存在（YNFactory-cc リポジトリ側）

## ディレクトリ構成

```
.claude-plugin/marketplace.json    マーケットプレイス定義
plugins/<plugin-name>/
├── .claude-plugin/plugin.json     プラグイン定義
├── skills/<skill-name>/SKILL.md   スキル本体
└── agents/<agent-name>.md         サブエージェント定義
```

スキルを追加・修正するときは該当プラグインの `skills/` 配下を編集し、新しいプラグインを足す場合は `plugins/` にディレクトリを作って `.claude-plugin/marketplace.json` の `plugins` 配列に追記します。

## 出自

これらのスキルは Google Drive の `YNFactory-cc` 作業ディレクトリで育ててきたものです。原本は Drive 側、または `yuichi4107-lab/YNFactory-cc` リポジトリの `.claude/skills` / `.agents/skills` にあります。ここへ集約したあとは、**このリポジトリを正本として扱う**のが管理上わかりやすくなります。
