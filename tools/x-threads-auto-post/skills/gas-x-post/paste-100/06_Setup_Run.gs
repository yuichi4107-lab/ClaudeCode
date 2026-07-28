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

