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
  if (!username) {
    throw new Error('NOTE_RSS_URL または NOTE_USERNAME をスクリプトプロパティに設定してください。');
  }
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
  if (!sheet) {
    throw new Error(`シート "${NOTE_RSS_BRIDGE.targetSheetName}" が見つかりません。先に setupSpreadsheet() を実行してください。`);
  }
  return sheet;
}

