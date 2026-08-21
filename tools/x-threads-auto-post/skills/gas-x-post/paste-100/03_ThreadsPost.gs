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

