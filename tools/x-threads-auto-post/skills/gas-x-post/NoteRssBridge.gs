/**
 * note公開検知 -> Codex処理待ち登録 GAS
 *
 * 使い方:
 * 1. 既存の Code.gs と同じ Apps Script プロジェクトに、このファイルの内容を追加する
 * 2. スクリプトプロパティを設定する
 *    - NOTE_RSS_URL または NOTE_USERNAME
 * 3. setupNoteRssBridge() を1回実行する
 * 4. dryRunNoteRssBridge() で確認する
 * 5. setupNoteRssBridgeTrigger() を実行して自動検知を開始する
 *
 * このファイルは「note公開検知」シートに新着noteを記録するだけです。
 * 投稿文生成はChatGPT Pro/Codex側で行い、生成後に「X投稿」シートへ予約行を追加します。
 * 外部AI APIキーは使いません。
 */

const NOTE_RSS_BRIDGE = Object.freeze({
  logSheetName: 'note公開検知',
  targetSheetName: 'X投稿',
  scanLimit: 5,
  social: Object.freeze({
    delayMinutes: 15,
    staggerMinutes: 180,
    xPostCount: 3,
    threadsPostCount: 1
  })
});

function setupNoteRssBridge() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const log = getOrCreateNoteRssLogSheet_(ss);
  if (log.getLastRow() === 0) {
    log.appendRow([
      '検知日時', '記事ID', 'タイトル', 'URL', '公開日時',
      '状態', 'X予約数', 'Threads予約数', 'エラー'
    ]);
    log.getRange(1, 1, 1, 9).setFontWeight('bold').setBackground('#f3f3f3');
    log.setColumnWidth(3, 260);
    log.setColumnWidth(4, 360);
    log.setColumnWidth(9, 360);
  }
  ensureTargetSheetExists_();
  console.log('note RSS連携の初期セットアップが完了しました。');
}

function setupNoteRssBridgeTrigger() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'pollNoteRssAndQueueSocialPosts')
    .forEach(t => ScriptApp.deleteTrigger(t));

  ScriptApp.newTrigger('pollNoteRssAndQueueSocialPosts')
    .timeBased()
    .everyHours(1)
    .create();

  console.log('note RSS連携トリガー設定完了: 1時間ごとに新着noteを確認します。');
}

function dryRunNoteRssBridge() {
  const props = PropertiesService.getScriptProperties();
  const rssUrl = getNoteRssUrl_(props);
  const items = fetchNoteRssItems_(rssUrl).slice(0, NOTE_RSS_BRIDGE.scanLimit);
  const seen = loadSeenNoteIds_();
  const fresh = items.filter(item => !seen.has(item.id));

  console.log(`RSS: ${rssUrl}`);
  console.log(`取得件数: ${items.length}`);
  console.log(`未処理件数: ${fresh.length}`);
  fresh.forEach((item, index) => {
    console.log(`[${index + 1}] ${item.title}`);
    console.log(`    ${item.url}`);
    console.log(`    published: ${item.publishedAt || ''}`);
  });
}

function pollNoteRssAndQueueSocialPosts() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    console.log('別のnote RSS連携処理が実行中のためスキップします。');
    return;
  }

  try {
    setupNoteRssBridge();

    const props = PropertiesService.getScriptProperties();
    const rssUrl = getNoteRssUrl_(props);
    const items = fetchNoteRssItems_(rssUrl).slice(0, NOTE_RSS_BRIDGE.scanLimit);
    const seen = loadSeenNoteIds_();

    const fresh = items
      .filter(item => !seen.has(item.id))
      .sort((a, b) => new Date(a.publishedAt || 0) - new Date(b.publishedAt || 0));

    if (fresh.length === 0) {
      console.log('新しいnote記事はありません。');
      return;
    }

    fresh.forEach(item => {
      queueSocialPostsForNote_(item, props);
    });
  } finally {
    lock.releaseLock();
  }
}

function queueSocialPostsForNote_(item, props) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const logSheet = getOrCreateNoteRssLogSheet_(ss);

  try {
    logSheet.appendRow([
      new Date(), item.id, item.title, item.url, item.publishedAt || '',
      'pending_codex', 0, 0, ''
    ]);
    console.log(`Codex処理待ちに追加: ${item.title}`);
  } catch (e) {
    logSheet.appendRow([
      new Date(), item.id, item.title, item.url, item.publishedAt || '',
      'error', 0, 0, e.message
    ]);
    console.error(`note連携エラー: ${e.message}`);
  }
}

function fetchNoteRssItems_(rssUrl) {
  const xml = UrlFetchApp.fetch(rssUrl, { muteHttpExceptions: true }).getContentText();
  const doc = XmlService.parse(xml);
  const root = doc.getRootElement();
  const channel = root.getChild('channel');
  if (!channel) throw new Error('RSS channel が見つかりません。NOTE_RSS_URL を確認してください。');

  return channel.getChildren('item').map(item => {
    const title = getChildText_(item, 'title');
    const link = getChildText_(item, 'link');
    const guid = getChildText_(item, 'guid') || link;
    return {
      id: guid,
      title,
      url: link,
      publishedAt: getChildText_(item, 'pubDate'),
      description: stripHtml_(getChildText_(item, 'description') || '')
    };
  }).filter(item => item.id && item.url && item.title);
}

function stripHtml_(value) {
  return String(value || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+\n/g, '\n')
    .replace(/\n\s+/g, '\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

function getChildText_(element, name) {
  const child = element.getChild(name);
  return child ? child.getText().trim() : '';
}

function getNoteRssUrl_(props) {
  const rssUrl = props.getProperty('NOTE_RSS_URL');
  if (rssUrl) return rssUrl;

  const username = props.getProperty('NOTE_USERNAME');
  if (!username) throw new Error('NOTE_RSS_URL または NOTE_USERNAME をスクリプトプロパティに設定してください。');
  return `https://note.com/${username}/rss`;
}

function loadSeenNoteIds_() {
  const sheet = getOrCreateNoteRssLogSheet_(SpreadsheetApp.getActiveSpreadsheet());
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return new Set();

  const values = sheet.getRange(2, 2, lastRow - 1, 1).getValues();
  return new Set(values.map(row => String(row[0] || '')).filter(Boolean));
}

function getOrCreateNoteRssLogSheet_(ss) {
  return ss.getSheetByName(NOTE_RSS_BRIDGE.logSheetName) || ss.insertSheet(NOTE_RSS_BRIDGE.logSheetName);
}

function ensureTargetSheetExists_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(NOTE_RSS_BRIDGE.targetSheetName);
  if (!sheet) throw new Error(`シート "${NOTE_RSS_BRIDGE.targetSheetName}" が見つかりません。先に setupSpreadsheet() を実行してください。`);
  return sheet;
}
