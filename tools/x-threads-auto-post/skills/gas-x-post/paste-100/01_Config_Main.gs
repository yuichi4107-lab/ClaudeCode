const CONFIG = Object.freeze({
  sheetName: 'X投稿',
  dataStartRow: 2,
  columns: Object.freeze({
    day: 1, hour: 2, minute: 3, content: 4,
    postToXFlag: 5, postToThreadsFlag: 6,
    image1: 7, image2: 8, image3: 9, image4: 10,
    postedFlag: 11, postedUrlX: 12, postedUrlThreads: 13
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

