/**
 * AIニュース配信システム - Google Docs アーカイブ用 GAS Webアプリ
 *
 * POSTリクエストを受け取り、Google Docsを作成して月別フォルダに整理する
 */

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);

    // 認証チェック
    var authToken = PropertiesService.getScriptProperties().getProperty("AUTH_TOKEN");
    if (!authToken || payload.token !== authToken) {
      return _jsonResponse({ error: "認証エラー: トークンが無効です" }, 403);
    }

    // バリデーション
    if (!payload.content) {
      return _jsonResponse({ error: "content は必須です" }, 400);
    }

    // タイトル決定
    var now = new Date();
    var title = payload.title || "AIニュースダイジェスト_" + Utilities.formatDate(now, "Asia/Tokyo", "yyyyMMdd");

    // 日付文字列から月別サブフォルダ名を決定 (例: "2026-04")
    var subFolderName;
    if (payload.date && /^\d{4}-\d{2}/.test(payload.date)) {
      subFolderName = payload.date.substring(0, 7);
    } else {
      subFolderName = Utilities.formatDate(now, "Asia/Tokyo", "yyyy-MM");
    }

    // ルートフォルダ取得
    var rootFolderId = PropertiesService.getScriptProperties().getProperty("ROOT_FOLDER_ID");
    if (!rootFolderId) {
      return _jsonResponse({ error: "ROOT_FOLDER_ID が設定されていません" }, 500);
    }
    var rootFolder = DriveApp.getFolderById(rootFolderId);

    // 月別サブフォルダを取得または作成
    var subFolder = _getOrCreateSubFolder(rootFolder, subFolderName);

    // Google Doc を作成
    var doc = DocumentApp.create(title);
    var docId = doc.getId();

    // 本文を挿入
    var body = doc.getBody();
    body.setText(payload.content);
    doc.saveAndClose();

    // サブフォルダに移動（マイドライブから移動）
    var file = DriveApp.getFileById(docId);
    subFolder.addFile(file);
    DriveApp.getRootFolder().removeFile(file);

    var docUrl = "https://docs.google.com/document/d/" + docId;
    return _jsonResponse({ success: true, url: docUrl, docId: docId });

  } catch (err) {
    return _jsonResponse({ error: "サーバーエラー: " + err.message }, 500);
  }
}

/**
 * 親フォルダ内にサブフォルダを取得、なければ作成する
 */
function _getOrCreateSubFolder(parentFolder, folderName) {
  var folders = parentFolder.getFoldersByName(folderName);
  if (folders.hasNext()) {
    return folders.next();
  }
  return parentFolder.createFolder(folderName);
}

/**
 * JSON レスポンスを返すヘルパー
 */
function _jsonResponse(data, statusCode) {
  // GAS の doPost は常に 200 を返すが、エラー情報は JSON に含める
  if (statusCode) {
    data.statusCode = statusCode;
  }
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
