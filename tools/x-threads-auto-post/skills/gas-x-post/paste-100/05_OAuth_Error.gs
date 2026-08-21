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

