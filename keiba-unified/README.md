# keiba-unified — 統合競馬予想システム

## 構成

```
keiba-unified/
├── shared/          共通基盤（Telegram、スクレイパー基底、ログ）
├── config/          統合設定
├── jra/             JRA中央競馬（馬連・三連複）
│   ├── src/         2026keiba由来のMLパイプライン（63特徴量、Optuna最適化）
│   ├── scripts/     keiba-predictor由来のライブモード・結果チェック
│   └── data/        DB・モデル・レポート
├── win5/            WIN5予想（予算最適化・Kelly基準）
│   ├── src/         7モジュール構成（CLI+Streamlit対応）
│   └── data/        win5.db
├── spat4/           地方競馬トリプル馬単
│   ├── data/        357開催分CSV
│   ├── scripts/     統計・パターン・オッズ分析
│   └── reports/     戦略書・分析レポート
├── data/            共有データ
└── scripts/         運用バッチ・タスクスケジューラXML
```

## 自動タスク一覧

### ばんえい競馬（D:\keiba-ai-system）
| タスク | 頻度 | 時刻 |
|--------|------|------|
| BaneiAI_Predict_1-5R | 毎日 | 13:30 |
| BaneiAI_Predict_6-12R | 毎日 | 16:30 |
| BaneiAI_CollectResults | 毎日 | 22:03 |
| BaneiAI_ReviewResults | 毎日 | 22:30 |

### JRA中央競馬（D:\keiba-unified）
| タスク | 頻度 | 時刻 |
|--------|------|------|
| KeibaUnified_JRA_Live | 毎週土日 | 09:30 |
| KeibaUnified_JRA_Results | 毎週土日 | 17:30 |
| KeibaUnified_JRA_Monthly | 毎月1日 | 10:00 |

## セットアップ
```bash
pip install -r requirements.txt
```
