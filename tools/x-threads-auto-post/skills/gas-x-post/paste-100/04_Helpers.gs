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

function fetchJson_(url, options, label) {
  const res = UrlFetchApp.fetch(url, { muteHttpExceptions: true, ...options });
  if (res.getResponseCode() >= 300) handleApiError_(res.getResponseCode(), res.getContentText(), label);
  return JSON.parse(res.getContentText());
}

