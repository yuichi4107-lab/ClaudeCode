/**
 * X自動投稿 GAS スクリプト
 * スプレッドシートの予約投稿データを時刻通りにXとThreadsへ投稿します。
 *
 * 【スプレッドシート列構成（1行目はヘッダー）】
 * A(1)  : 投稿日          例: 2026/3/23
 * B(2)  : 時              例: 7
 * C(3)  : 分              例: 0
 * D(4)  : 投稿内容
 * E(5)  : X投稿する       チェックボックス (TRUE/FALSE)
 * F(6)  : Threads投稿する チェックボックス (TRUE/FALSE)
 * G(7)  : 画像1 URL       任意
 * H(8)  : 画像2 URL       任意
 * I(9)  : 画像3 URL       任意
 * J(10) : 画像4 URL       任意
 * K(11) : 投稿済み        チェックボックス (自動記入)
 * L(12) : X投稿URL        自動記入
 * M(13) : Threads投稿URL  自動記入
 */

const CONFIG = Object.freeze({
  sheetName: 'X投稿',
  dataStartRow: 2,
  columns: Object.freeze({
    day: 1,               // A列: 投稿日
    hour: 2,              // B列: 時
    minute: 3,            // C列: 分
    content: 4,           // D列: 投稿内容
    postToXFlag: 5,       // E列: X投稿する
    postToThreadsFlag: 6, // F列: Threads投稿する
    image1: 7,            // G列: 画像1 URL
    image2: 8,            // H列: 画像2 URL
    image3: 9,            // I列: 画像3 URL
    image4: 10,           // J列: 画像4 URL
    postedFlag: 11,       // K列: 投稿済みフラグ (TRUE)
    postedUrlX: 12,       // L列: X投稿URL
    postedUrlThreads: 13  // M列: Threads投稿URL
  }),
  api: Object.freeze({
    xTweet: 'https://api.twitter.com/2/tweets',
    xUpload: 'https://upload.twitter.com/1.1/media/upload.json',
    threadsBase: 'https://graph.threads.net/v1.0'
  }),
  serialBaseDate: new Date(1899, 11, 30)
});

// ===========================================================
// エントリーポイント（時間トリガーで毎時または30分ごとに実行）
// ===========================================================

/**
 * メイン実行関数。未投稿・時刻到達済みの行を1件処理する。
 */
function postNextScheduledItem() {
  const sheet = getTargetSheet_();
  const target = findNextPublishableRow_(sheet);

  if (!target) {
    console.log('投稿対象なし。');
    return;
  }

  const { rowNumber, content, postToX, postToThreads,
          xUrlExists, threadsUrlExists,
          image1, image2, image3, image4 } = target;

  const props = PropertiesService.getScriptProperties();

  // --- X への投稿 ---
  if (postToX && !xUrlExists) {
    try {
      console.log(`行 ${rowNumber}: X投稿開始...`);
      const xUrl = postToX_(content, [image1, image2, image3, image4], props);
      sheet.getRange(rowNumber, CONFIG.columns.postedUrlX).setValue(xUrl);
      console.log(`X投稿成功: ${xUrl}`);
    } catch (e) {
      console.error(`X投稿エラー: ${e.message}`);
      sheet.getRange(rowNumber, CONFIG.columns.postedUrlX).setValue(`エラー: ${e.message}`);
    }
  }

  // --- Threads への投稿 ---
  if (postToThreads && !threadsUrlExists) {
    try {
      console.log(`行 ${rowNumber}: Threads投稿開始...`);
      const threadsUrl = postToThreads_(content, props);
      sheet.getRange(rowNumber, CONFIG.columns.postedUrlThreads).setValue(threadsUrl);
      console.log(`Threads投稿成功: ${threadsUrl}`);
    } catch (e) {
      console.error(`Threads投稿エラー: ${e.message}`);
      sheet.getRange(rowNumber, CONFIG.columns.postedUrlThreads).setValue(`エラー: ${e.message}`);
    }
  }

  // --- 完了フラグ更新 ---
  // URL欄が埋まった（or 対象外）なら投稿済みとマーク
  const xDone    = !postToX      || sheet.getRange(rowNumber, CONFIG.columns.postedUrlX).getValue() !== '';
  const thdDone  = !postToThreads || sheet.getRange(rowNumber, CONFIG.columns.postedUrlThreads).getValue() !== '';
  if (xDone && thdDone) {
    sheet.getRange(rowNumber, CONFIG.columns.postedFlag).setValue(true);
    console.log(`行 ${rowNumber}: 投稿完了マーク済み。`);
  }
}

// ===========================================================
// X投稿
// ===========================================================

function postToX_(content, images, props) {
  const apiKey            = props.getProperty('X_API_KEY');
  const apiSecret         = props.getProperty('X_API_SECRET');
  const accessToken       = props.getProperty('X_ACCESS_TOKEN');
  const accessTokenSecret = props.getProperty('X_ACCESS_TOKEN_SECRET');

  if (!apiKey || !apiSecret || !accessToken || !accessTokenSecret) {
    throw new Error('X用APIキーがスクリプトプロパティに設定されていません。');
  }

  const keys = { apiKey, apiSecret, accessToken, accessTokenSecret };
  const mediaIds = [];
  const imageUrls = images.filter(url => url && typeof url === 'string' && url.startsWith('http'));

  for (const imgUrl of imageUrls) {
    const blob = UrlFetchApp.fetch(imgUrl).getBlob();
    mediaIds.push(uploadMediaToX_(blob, keys));
  }

  const payload = { text: content };
  if (mediaIds.length > 0) payload.media = { media_ids: mediaIds };

  const oauthBase = { oauth_consumer_key: apiKey, oauth_token: accessToken };
  const authHeader = buildOAuthHeader_('POST', CONFIG.api.xTweet, oauthBase, apiSecret, accessTokenSecret);

  const res = UrlFetchApp.fetch(CONFIG.api.xTweet, {
    method: 'POST',
    muteHttpExceptions: true,
    headers: { Authorization: authHeader, 'Content-Type': 'application/json' },
    payload: JSON.stringify(payload)
  });

  const body = res.getContentText();
  if (res.getResponseCode() >= 300) handleApiError_(res.getResponseCode(), body, 'X');

  return `https://x.com/i/web/status/${JSON.parse(body).data.id}`;
}

// ===========================================================
// Threads投稿
// ===========================================================

function postToThreads_(content, props) {
  const accessToken = props.getProperty('THREADS_ACCESS_TOKEN');
  let userId = props.getProperty('THREADS_USER_ID');

  if (!accessToken) throw new Error('THREADS_ACCESS_TOKEN が設定されていません。');

  if (!userId) {
    const profile = fetchJson_(
      `${CONFIG.api.threadsBase}/me?fields=id,username&access_token=${encodeURIComponent(accessToken)}`,
      { method: 'get' }, 'Threadsプロファイル取得'
    );
    if (!profile || !profile.id) throw new Error('ThreadsユーザーIDを取得できませんでした。');
    userId = String(profile.id);
    props.setProperty('THREADS_USER_ID', userId);
  }

  const draft = fetchJson_(
    `${CONFIG.api.threadsBase}/${encodeURIComponent(userId)}/threads`,
    { method: 'post', payload: { media_type: 'TEXT', text: content, access_token: accessToken } },
    'Threadsドラフト作成'
  );
  if (!draft || !draft.id) throw new Error('ThreadsドラフトIDが返されませんでした。');

  const pub = fetchJson_(
    `${CONFIG.api.threadsBase}/${encodeURIComponent(userId)}/threads_publish`,
    { method: 'post', payload: { creation_id: draft.id, access_token: accessToken } },
    'Threads投稿実行'
  );
  if (!pub || !pub.id) throw new Error('Threads投稿IDが返されませんでした。');

  try {
    const perma = fetchJson_(
      `${CONFIG.api.threadsBase}/${pub.id}?fields=permalink&access_token=${encodeURIComponent(accessToken)}`,
      { method: 'get' }, 'Threads URL取得'
    );
    return perma.permalink || 'URL取得失敗';
  } catch (e) {
    return 'URL取得失敗(投稿は成功)';
  }
}

// ===========================================================
// 内部ヘルパー
// ===========================================================

function getTargetSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.sheetName);
  if (!sheet) throw new Error(`シート "${CONFIG.sheetName}" が見つかりません。`);
  return sheet;
}

function findNextPublishableRow_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.dataStartRow) return null;

  const numCols = CONFIG.columns.postedUrlThreads;
  const data = sheet.getRange(CONFIG.dataStartRow, 1, lastRow - CONFIG.dataStartRow + 1, numCols).getValues();
  const now = new Date();

  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const rowNum = CONFIG.dataStartRow + i;

    if (String(row[CONFIG.columns.postedFlag - 1]).toUpperCase() === 'TRUE') continue;

    const postToX       = row[CONFIG.columns.postToXFlag - 1] === true;
    const postToThreads = row[CONFIG.columns.postToThreadsFlag - 1] === true;
    if (!postToX && !postToThreads) continue;

    const scheduledAt = parseDate_(
      row[CONFIG.columns.day - 1],
      row[CONFIG.columns.hour - 1],
      row[CONFIG.columns.minute - 1]
    );
    if (!scheduledAt || scheduledAt > now) continue;

    const content = String(row[CONFIG.columns.content - 1] || '').trim();
    if (!content) continue;

    return {
      rowNumber: rowNum,
      content,
      scheduledAt,
      postToX,
      postToThreads,
      xUrlExists:      !!row[CONFIG.columns.postedUrlX - 1],
      threadsUrlExists: !!row[CONFIG.columns.postedUrlThreads - 1],
      image1: row[CONFIG.columns.image1 - 1],
      image2: row[CONFIG.columns.image2 - 1],
      image3: row[CONFIG.columns.image3 - 1],
      image4: row[CONFIG.columns.image4 - 1]
    };
  }
  return null;
}

function parseDate_(dayVal, hourVal, minVal) {
  if (!dayVal) return null;
  let date = new Date(dayVal);
  if (isNaN(date.getTime())) {
    if (typeof dayVal === 'number') {
      date = new Date(CONFIG.serialBaseDate.getTime() + dayVal * 86400000);
    } else return null;
  }
  date.setHours(hourVal || 0, minVal || 0, 0, 0);
  return date;
}

function uploadMediaToX_(blob, keys) {
  const authHeader = buildOAuthHeader_(
    'POST', CONFIG.api.xUpload,
    { oauth_consumer_key: keys.apiKey, oauth_token: keys.accessToken },
    keys.apiSecret, keys.accessTokenSecret
  );
  const res = UrlFetchApp.fetch(CONFIG.api.xUpload, {
    method: 'POST',
    muteHttpExceptions: true,
    headers: { Authorization: authHeader },
    payload: { media: blob }
  });
  if (res.getResponseCode() >= 300) handleApiError_(res.getResponseCode(), res.getContentText(), 'X Media Upload');
  return JSON.parse(res.getContentText()).media_id_string;
}

function buildOAuthHeader_(method, url, oauthParams, apiSecret, tokenSecret) {
  const params = {
    ...oauthParams,
    oauth_nonce: Utilities.getUuid().replace(/-/g, ''),
    oauth_signature_method: 'HMAC-SHA1',
    oauth_timestamp: Math.floor(Date.now() / 1000).toString(),
    oauth_version: '1.0'
  };
  const base = [
    method,
    encodeURIComponent(url),
    encodeURIComponent(Object.keys(params).sort().map(k => `${k}=${params[k]}`).join('&'))
  ].join('&');
  params.oauth_signature = Utilities.base64Encode(
    Utilities.computeHmacSignature(
      Utilities.MacAlgorithm.HMAC_SHA_1,
      base,
      `${encodeURIComponent(apiSecret)}&${encodeURIComponent(tokenSecret)}`
    )
  );
  return 'OAuth ' + Object.keys(params).sort().map(k => `${k}="${encodeURIComponent(params[k])}"`).join(', ');
}

function handleApiError_(code, body, label) {
  let msg = `${label} API Error ${code}: ${body}`;
  try {
    const json = JSON.parse(body);
    if (json.detail)                msg = `${label}: ${json.detail}`;
    if (json.errors)                msg = `${label}: ${json.errors[0].message}`;
    if (json.error?.message)        msg = `${label}: ${json.error.message}`;
  } catch (_) {}
  throw new Error(msg);
}

function fetchJson_(url, options, label) {
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, ...options });
  if (res.getResponseCode() >= 300) handleApiError_(res.getResponseCode(), res.getContentText(), label);
  return JSON.parse(res.getContentText());
}

// ===========================================================
// セットアップ補助（手動で一度だけ実行）
// ===========================================================

/**
 * スプレッドシートのシートを初期化する（手動で一度だけ実行）
 * - 「X投稿」シートを作成（既存なら上書き確認なしでスキップ）
 * - ヘッダー行を設定
 * - チェックボックス列を設定
 * - 初期データ（5件）を投入
 */
function setupSpreadsheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // シートを取得 or 作成
  let sheet = ss.getSheetByName(CONFIG.sheetName);
  if (sheet) {
    const ui = SpreadsheetApp.getUi();
    const res = ui.alert(
      `シート "${CONFIG.sheetName}" は既に存在します。`,
      '上書きしますか？（データが全て消えます）',
      ui.ButtonSet.YES_NO
    );
    if (res !== ui.Button.YES) {
      console.log('キャンセルしました。');
      return;
    }
    sheet.clearContents();
    sheet.clearFormats();
  } else {
    sheet = ss.insertSheet(CONFIG.sheetName);
  }

  // ヘッダー行
  const headers = [
    '投稿日', '時', '分', '投稿内容',
    'X投稿する', 'Threads投稿する',
    '画像1URL', '画像2URL', '画像3URL', '画像4URL',
    '投稿済み', 'X投稿URL', 'Threads投稿URL'
  ];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length)
    .setFontWeight('bold')
    .setBackground('#f3f3f3');

  // チェックボックス列（E, F, K）
  const lastDataRow = 100; // 最大100行分設定
  sheet.getRange(2, CONFIG.columns.postToXFlag, lastDataRow, 1)
    .insertCheckboxes();
  sheet.getRange(2, CONFIG.columns.postToThreadsFlag, lastDataRow, 1)
    .insertCheckboxes();
  sheet.getRange(2, CONFIG.columns.postedFlag, lastDataRow, 1)
    .insertCheckboxes();

  // 列幅を調整
  sheet.setColumnWidth(CONFIG.columns.content, 400);
  sheet.setColumnWidth(CONFIG.columns.postedUrlX, 200);
  sheet.setColumnWidth(CONFIG.columns.postedUrlThreads, 200);

  // 初期データ（5件）
  const posts = [
    [
      '2026/3/23', 7, 0,
      '「AntigravityってClaude Codeに勝てるの？」とか言いながら、実は乗り遅れるのが怖いだけの人へ。\n\nGoogleが完全無料でぶっ込んできたAI IDE、1週間本気で使い込んだ。\n\n結論：今すぐ乗り換えじゃないけど、無視できない理由がある。\n\n詳細↓\nhttps://note.com/your_username/n/your_article_id\n\n#AI開発 #ClaudeCode #Antigravity',
      true, false, '', '', '', '', false, '', ''
    ],
    [
      '2026/3/23', 12, 0,
      'Antigravityを触って「あ、Googleが本気だな」と思った瞬間。\n\nAIエージェントを複数並列実行できる\n→ Claude Codeは基本1タスク順番待ち\n\nブラウザテストが最初から内蔵\n→ Playwrightを自前設定してた俺、何してたんだろうw\n\n完全無料（プレビュー中）\n→ いつ課金に切り替わるか不明。今のうちに触っとく価値はある。\n\nhttps://note.com/your_username/n/your_article_id\n\n#Antigravity #AI開発ツール',
      true, false, '', '', '', '', false, '', ''
    ],
    [
      '2026/3/23', 19, 0,
      'Claude Codeが向いてる案件\n→ 既存の大規模コード改修、本番環境・安全性重視、チーム開発・MCP連携\n\nAntigravityが向いてる案件\n→ フロントエンドの新規開発、ブラウザ動作を繰り返し確認する作業、「とにかく今すぐ無料で試したい」\n\nどちらが上じゃない。用途次第。\n\nhttps://note.com/your_username/n/your_article_id\n\n#AIツール #エンジニア',
      true, false, '', '', '', '', false, '', ''
    ],
    [
      '2026/3/23', 21, 0,
      '正直に言う。\n\n今の業務ならClaude Code一択。コードベース全体を200kトークンで把握する力は、大きいリポジトリで特に差が出る。\n\nただ。\n\nAntigravityはフロントエンドとブラウザテスト文脈で急成長してる。Googleのインフラ力は正直脅威。\n\n半年後に「あのとき触っとけばよかった」はなりたくない。今のうちに両方知っておく価値はある。\n\nhttps://note.com/your_username/n/your_article_id\n\n#ClaudeCode #Antigravity',
      true, false, '', '', '', '', false, '', ''
    ],
    [
      '2026/3/24', 7, 0,
      'Claude Code vs Antigravity、整理した。\n\nClaude Code\n→ $20/月〜 / 200kトークンでコードベース全理解 / 本番・チーム・MCP連携向き\n\nAntigravity\n→ 完全無料（プレビュー中）/ 自律エージェント並列実行 / フロントエンド・自動化向き\n\nどちらが上じゃない。「何を作るか」で使い分けるだけ。\n\nhttps://note.com/your_username/n/your_article_id\n\n#AI #開発効率化 #プログラミング',
      true, false, '', '', '', '', false, '', ''
    ]
  ];

  sheet.getRange(2, 1, posts.length, headers.length).setValues(posts);

  // 投稿内容列（D列）は折り返し表示
  sheet.getRange(2, CONFIG.columns.content, posts.length, 1)
    .setWrap(true);

  console.log(`✅ セットアップ完了: ${posts.length}件のデータを投入しました。`);
  SpreadsheetApp.getUi().alert('セットアップ完了！\n\n次に setupTrigger() を実行してトリガーを登録してください。');
}

/**
 * 時間トリガーを登録する（手動で一度だけ実行）
 * 30分ごとに postNextScheduledItem を実行
 */
function setupTrigger() {
  // 既存トリガーを削除
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'postNextScheduledItem')
    .forEach(t => ScriptApp.deleteTrigger(t));

  // 30分ごとのトリガーを新規作成
  ScriptApp.newTrigger('postNextScheduledItem')
    .timeBased()
    .everyMinutes(30)
    .create();

  console.log('トリガー設定完了: 30分ごとに postNextScheduledItem を実行します。');
}

/**
 * 動作確認用ドライラン（シートを変更せずに次の投稿対象を確認）
 */
function dryRun() {
  const sheet = getTargetSheet_();
  const target = findNextPublishableRow_(sheet);
  if (!target) {
    console.log('投稿対象なし。');
    return;
  }
  console.log('--- 次の投稿対象 ---');
  console.log(`行: ${target.rowNumber}`);
  console.log(`予定時刻: ${target.scheduledAt}`);
  console.log(`X投稿: ${target.postToX} / Threads投稿: ${target.postToThreads}`);
  console.log(`内容:\n${target.content}`);
}
