# 名古屋天気

名古屋市をデフォルト表示するスマホ向け静的Web天気アプリです。

## 使い方

```bash
cd weather-nagoya-app
python3 -m http.server 4173
```

同じWi-Fi内のスマホから見る場合は、MacのIPアドレスを使って `http://<MacのIP>:4173/` を開きます。

## 仕様

- 初期地点: 名古屋市 `35.1815, 136.9066`
- 天気API: Open-Meteo Forecast API
- 表示内容: 現在の天気、体感温度、降水量、湿度、風速、12時間予報、7日間予報
- PWA対応: manifest と service worker を同梱

## 注意

スマホで現在地ボタンを使うには、HTTPS配信または `localhost` 相当の安全な接続が必要です。名古屋市の初期表示と更新は通常のHTTPでも動作します。
