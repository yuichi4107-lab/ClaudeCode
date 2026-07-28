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

