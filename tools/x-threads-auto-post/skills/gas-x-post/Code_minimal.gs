/**
 * X/Threads 自動投稿 GAS 短縮版
 * サンプル投稿なし。Apps Scriptに貼り付けやすい版です。
 */

const CONFIG = Object.freeze({
  sheetName: 'X投稿',
  dataStartRow: 2,
  columns: Object.freeze({
    day: 1,
    hour: 2,
    minute: 3,
    content: 4,
    postToXFlag: 5,
    postToThreadsFlag: 6,
    image1: 7,
    image2: 8,
    image3: 9,
    image4: 10,
    postedFlag: 11,
    postedUrlX: 12,
    postedUrlThreads: 13
  }),
  api: Object.freeze({
    xTweet: 'https://api.twitter.com/2/tweets',
    xUpload: 'https://upload.twitter.com/1.1/media/upload.json',
    threadsBase: 'https://graph.threads.net/v1.0'
  }),
  serialBaseDate: new Date(1899, 11, 30)
});

function postNextScheduledItem() {
  const sheet = getTargetSheet_();
  const target = findNextPublishableRow_(sheet);
  if (!target) {
    console.log('投稿対象なし。');
    return;
  }

  const props = PropertiesService.getScriptProperties();

  if (target.postToX && !target.xUrlExists) {
    try {
      const xUrl = postToX_(
        target.content,
        [target.image1, target.image2, target.image3, target.image4],
        props
      );
      sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlX).setValue(xUrl);
      console.log(`X投稿成功: ${xUrl}`);
    } catch (e) {
      console.error(`X投稿エラー: ${e.message}`);
      sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlX).setValue(`エラー: ${e.message}`);
    }
  }

  if (target.postToThreads && !target.threadsUrlExists) {
    try {
      const threadsUrl = postToThreads_(target.content, props);
      sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlThreads).setValue(threadsUrl);
      console.log(`Threads投稿成功: ${threadsUrl}`);
    } catch (e) {
      console.error(`Threads投稿エラー: ${e.message}`);
      sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlThreads).setValue(`エラー: ${e.message}`);
    }
  }

  const xDone = !target.postToX || sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlX).getValue() !== '';
  const threadsDone = !target.postToThreads || sheet.getRange(target.rowNumber, CONFIG.columns.postedUrlThreads).getValue() !== '';
  if (xDone && threadsDone) {
    sheet.getRange(target.rowNumber, CONFIG.columns.postedFlag).setValue(true);
  }
}

function postToX_(content, images, props) {
  const apiKey = props.getProperty('X_API_KEY');
  const apiSecret = props.getProperty('X_API_SECRET');
  const accessToken = props.getProperty('X_ACCESS_TOKEN');
  const accessTokenSecret = props.getProperty('X_ACCESS_TOKEN_SECRET');

  if (!apiKey || !apiSecret || !accessToken || !accessTokenSecret) {
    throw new Error('X用APIキーがスクリプトプロパティに設定されていません。');
  }

  const keys = { apiKey, apiSecret, accessToken, accessTokenSecret };
  const mediaIds = [];
  const imageUrls = images.filter(url => url && typeof url === 'string' && url.startsWith('http'));

  imageUrls.forEach(url => {
    const blob = UrlFetchApp.fetch(url).getBlob();
    mediaIds.push(uploadMediaToX_(blob, keys));
  });

  const payload = { text: content };
  if (mediaIds.length > 0) payload.media = { media_ids: mediaIds };

  const authHeader = buildOAuthHeader_(
    'POST',
    CONFIG.api.xTweet,
    { oauth_consumer_key: apiKey, oauth_token: accessToken },
    apiSecret,
    accessTokenSecret
  );

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

function postToThreads_(content, props) {
  const accessToken = props.getProperty('THREADS_ACCESS_TOKEN');
  let userId = props.getProperty('THREADS_USER_ID');
  if (!accessToken) throw new Error('THREADS_ACCESS_TOKEN が設定されていません。');

  if (!userId) {
    const profile = fetchJson_(
      `${CONFIG.api.threadsBase}/me?fields=id,username&access_token=${encodeURIComponent(accessToken)}`,
      { method: 'get' },
      'Threadsプロファイル取得'
    );
    userId = String(profile.id || '');
    if (!userId) throw new Error('ThreadsユーザーIDを取得できませんでした。');
    props.setProperty('THREADS_USER_ID', userId);
  }

  const draft = fetchJson_(
    `${CONFIG.api.threadsBase}/${encodeURIComponent(userId)}/threads`,
    { method: 'post', payload: { media_type: 'TEXT', text: content, access_token: accessToken } },
    'Threadsドラフト作成'
  );

  const pub = fetchJson_(
    `${CONFIG.api.threadsBase}/${encodeURIComponent(userId)}/threads_publish`,
    { method: 'post', payload: { creation_id: draft.id, access_token: accessToken } },
    'Threads投稿実行'
  );

  try {
    const perma = fetchJson_(
      `${CONFIG.api.threadsBase}/${pub.id}?fields=permalink&access_token=${encodeURIComponent(accessToken)}`,
      { method: 'get' },
      'Threads URL取得'
    );
    return perma.permalink || 'URL取得失敗';
  } catch (e) {
    return 'URL取得失敗(投稿は成功)';
  }
}

function getTargetSheet_() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.sheetName);
  if (!sheet) throw new Error(`シート "${CONFIG.sheetName}" が見つかりません。`);
  return sheet;
}

function findNextPublishableRow_(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.dataStartRow) return null;

  const data = sheet
    .getRange(CONFIG.dataStartRow, 1, lastRow - CONFIG.dataStartRow + 1, CONFIG.columns.postedUrlThreads)
    .getValues();
  const now = new Date();

  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const rowNumber = CONFIG.dataStartRow + i;
    if (String(row[CONFIG.columns.postedFlag - 1]).toUpperCase() === 'TRUE') continue;

    const postToX = row[CONFIG.columns.postToXFlag - 1] === true;
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
      rowNumber,
      content,
      scheduledAt,
      postToX,
      postToThreads,
      xUrlExists: !!row[CONFIG.columns.postedUrlX - 1],
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
    } else {
      return null;
    }
  }
  date.setHours(hourVal || 0, minVal || 0, 0, 0);
  return date;
}

function uploadMediaToX_(blob, keys) {
  const authHeader = buildOAuthHeader_(
    'POST',
    CONFIG.api.xUpload,
    { oauth_consumer_key: keys.apiKey, oauth_token: keys.accessToken },
    keys.apiSecret,
    keys.accessTokenSecret
  );
  const res = UrlFetchApp.fetch(CONFIG.api.xUpload, {
    method: 'POST',
    muteHttpExceptions: true,
    headers: { Authorization: authHeader },
    payload: { media: blob }
  });
  if (res.getResponseCode() >= 300) {
    handleApiError_(res.getResponseCode(), res.getContentText(), 'X Media Upload');
  }
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
    if (json.detail) msg = `${label}: ${json.detail}`;
    if (json.errors) msg = `${label}: ${json.errors[0].message}`;
    if (json.error && json.error.message) msg = `${label}: ${json.error.message}`;
  } catch (_) {}
  throw new Error(msg);
}

function fetchJson_(url, options, label) {
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, ...options });
  if (res.getResponseCode() >= 300) handleApiError_(res.getResponseCode(), res.getContentText(), label);
  return JSON.parse(res.getContentText());
}

function setupSpreadsheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(CONFIG.sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.sheetName);
  } else {
    sheet.clearContents();
    sheet.clearFormats();
  }

  const headers = [
    '投稿日', '時', '分', '投稿内容',
    'X投稿する', 'Threads投稿する',
    '画像1URL', '画像2URL', '画像3URL', '画像4URL',
    '投稿済み', 'X投稿URL', 'Threads投稿URL'
  ];
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  sheet.getRange(1, 1, 1, headers.length).setFontWeight('bold').setBackground('#f3f3f3');
  sheet.getRange(2, CONFIG.columns.postToXFlag, 200, 1).insertCheckboxes();
  sheet.getRange(2, CONFIG.columns.postToThreadsFlag, 200, 1).insertCheckboxes();
  sheet.getRange(2, CONFIG.columns.postedFlag, 200, 1).insertCheckboxes();
  sheet.setColumnWidth(CONFIG.columns.content, 420);
  sheet.setColumnWidth(CONFIG.columns.postedUrlX, 220);
  sheet.setColumnWidth(CONFIG.columns.postedUrlThreads, 220);
  console.log('X投稿シートを初期化しました。サンプル投稿は投入していません。');
}

function setupTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'postNextScheduledItem')
    .forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('postNextScheduledItem').timeBased().everyMinutes(30).create();
  console.log('トリガー設定完了: 30分ごとに postNextScheduledItem を実行します。');
}

function dryRun() {
  const target = findNextPublishableRow_(getTargetSheet_());
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
