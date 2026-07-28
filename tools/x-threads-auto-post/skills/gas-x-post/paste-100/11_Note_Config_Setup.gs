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
    fresh.forEach(item => queueSocialPostsForNote_(item));
  } finally {
    lock.releaseLock();
  }
}

function queueSocialPostsForNote_(item) {
  const logSheet = getOrCreateNoteRssLogSheet_(SpreadsheetApp.getActiveSpreadsheet());
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

