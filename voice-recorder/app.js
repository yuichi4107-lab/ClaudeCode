/**
 * 音声録音アプリ - app.js
 * バニラJS + MediaRecorder API + Web Audio API AnalyserNode + IndexedDB
 */

'use strict';

/* ===================================
   定数・設定
   =================================== */
const DB_NAME = 'VoiceRecorderDB';
const DB_VERSION = 1;
const STORE_NAME = 'recordings';

/* ===================================
   状態管理
   =================================== */
const state = {
  /** @type {'idle'|'recording'|'paused'} */
  mode: 'idle',
  mediaRecorder: null,
  audioChunks: [],
  stream: null,
  audioContext: null,
  analyser: null,
  sourceNode: null,
  animationFrameId: null,
  timerIntervalId: null,
  elapsedMs: 0,  // 録音中の累積経過ミリ秒
  timerStartedAt: null,  // 現在のセグメント開始時刻
};

/* ===================================
   DOM 参照
   =================================== */
const dom = {
  errorBanner:     () => document.getElementById('error-banner'),
  errorMessage:    () => document.getElementById('error-message'),
  errorClose:      () => document.getElementById('error-close'),
  micSelect:       () => document.getElementById('mic-select'),
  refreshDevices:  () => document.getElementById('refresh-devices'),
  timer:           () => document.getElementById('timer'),
  recDot:          () => document.getElementById('rec-dot'),
  visualizer:      () => document.getElementById('visualizer'),
  visualizerHint:  () => document.getElementById('visualizer-hint'),
  btnRecord:       () => document.getElementById('btn-record'),
  btnPause:        () => document.getElementById('btn-pause'),
  btnStop:         () => document.getElementById('btn-stop'),
  recordingStatus: () => document.getElementById('recording-status'),
  recordingList:   () => document.getElementById('recording-list'),
  emptyMessage:    () => document.getElementById('empty-message'),
  recordingsCount: () => document.getElementById('recordings-count'),
  itemTemplate:    () => document.getElementById('recording-item-tpl'),
};

/* ===================================
   エラー表示
   =================================== */

/**
 * 画面上部にエラーバナーを表示する
 * @param {string} message
 */
function showError(message) {
  dom.errorMessage().textContent = message;
  dom.errorBanner().classList.remove('hidden');
}

function hideError() {
  dom.errorBanner().classList.add('hidden');
  dom.errorMessage().textContent = '';
}

/* ===================================
   ブラウザ対応チェック
   =================================== */

/**
 * MediaRecorder / Web Audio API の対応状況を確認し、
 * 非対応の場合は警告を表示して録音ボタンを無効化する
 * @returns {boolean}
 */
function checkBrowserSupport() {
  // file:// で直接開かれた場合（マイクはセキュアコンテキスト必須のため使えない）
  if (location.protocol === 'file:') {
    showError('このファイルを直接開いています。録音機能はブラウザのセキュリティ仕様により、ローカルサーバ経由（http://localhost）でしか動作しません。同じフォルダの「start.bat」をダブルクリックして起動してください（自動でブラウザが開きます）。');
    dom.btnRecord().disabled = true;
    return false;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showError('お使いのブラウザは録音に対応していません。Chrome / Firefox / Safari の最新版をご利用ください。');
    dom.btnRecord().disabled = true;
    return false;
  }
  if (typeof MediaRecorder === 'undefined') {
    showError('お使いのブラウザは MediaRecorder API に対応していません。Chrome または Firefox をご利用ください。');
    dom.btnRecord().disabled = true;
    return false;
  }
  if (typeof AudioContext === 'undefined' && typeof webkitAudioContext === 'undefined') {
    showError('お使いのブラウザは Web Audio API に対応していません。波形表示は利用できません。');
    // 録音自体は続行可能なので無効化しない
  }
  return true;
}

/* ===================================
   マイクデバイス選択
   =================================== */

/**
 * 利用可能なオーディオ入力デバイスを列挙して <select> に反映する
 */
async function loadAudioDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const audioInputs = devices.filter(d => d.kind === 'audioinput');

    const sel = dom.micSelect();
    // 現在の選択値を保持
    const currentValue = sel.value;

    // デフォルト以外のオプションをクリア
    while (sel.options.length > 1) sel.remove(1);

    audioInputs.forEach((device, index) => {
      const option = document.createElement('option');
      option.value = device.deviceId;
      option.textContent = device.label || `マイク ${index + 1}`;
      sel.appendChild(option);
    });

    // 以前の選択を復元
    if (currentValue && [...sel.options].some(o => o.value === currentValue)) {
      sel.value = currentValue;
    }
  } catch (err) {
    console.warn('デバイス列挙失敗:', err);
  }
}

/* ===================================
   録音コア（MediaRecorder）
   =================================== */

/**
 * 録音を開始する
 * getUserMedia でマイクを取得し、MediaRecorder + AnalyserNode を設定する
 */
async function startRecording() {
  hideError();

  const deviceId = dom.micSelect().value;
  const audioConstraints = deviceId
    ? { deviceId: { exact: deviceId } }
    : true;

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
  } catch (err) {
    handleGetUserMediaError(err);
    return;
  }

  // デバイスリストを更新（label が取得できるのは権限取得後）
  await loadAudioDevices();

  state.stream = stream;
  state.audioChunks = [];

  // MediaRecorder 初期化
  const mimeType = getSupportedMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
  state.mediaRecorder = recorder;

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) {
      state.audioChunks.push(e.data);
    }
  };

  recorder.onstop = handleRecordingStop;
  recorder.start(100); // 100ms ごとにデータチャンク

  // Web Audio AnalyserNode セットアップ
  setupAnalyser(stream);

  // 状態を録音中に変更
  state.mode = 'recording';
  state.elapsedMs = 0;
  state.timerStartedAt = Date.now();
  updateUI();
  startTimer();
  startVisualizer();

  dom.recordingStatus().textContent = '録音中...';
}

/**
 * 録音を一時停止 / 再開する
 */
function togglePause() {
  if (state.mode === 'recording') {
    // 一時停止
    state.mediaRecorder.pause();
    state.elapsedMs += Date.now() - state.timerStartedAt;
    state.timerStartedAt = null;
    state.mode = 'paused';
    stopTimer();
    stopVisualizer();
    dom.recordingStatus().textContent = '一時停止中';
    dom.btnPause().innerHTML = '<span class="btn-icon" aria-hidden="true">&#9654;</span> 再開';
    dom.btnPause().setAttribute('aria-label', '録音を再開する');
    dom.recDot().classList.add('hidden');

  } else if (state.mode === 'paused') {
    // 再開
    state.mediaRecorder.resume();
    state.timerStartedAt = Date.now();
    state.mode = 'recording';
    startTimer();
    startVisualizer();
    dom.recordingStatus().textContent = '録音中...';
    dom.btnPause().innerHTML = '<span class="btn-icon" aria-hidden="true">&#9646;&#9646;</span> 一時停止';
    dom.btnPause().setAttribute('aria-label', '録音を一時停止する');
    dom.recDot().classList.remove('hidden');
  }
}

/**
 * 録音を停止する
 */
function stopRecording() {
  if (state.mode === 'paused') {
    // 一時停止中に停止した場合、timerStartedAt は既に null
  } else {
    state.elapsedMs += Date.now() - state.timerStartedAt;
  }
  state.timerStartedAt = null;
  state.mediaRecorder.stop();
  stopTimer();
  stopVisualizer();

  // ストリームのトラックを解放
  state.stream.getTracks().forEach(t => t.stop());

  state.mode = 'idle';
  updateUI();
  dom.recordingStatus().textContent = '録音を保存しました';
  dom.recDot().classList.add('hidden');
  dom.btnPause().innerHTML = '<span class="btn-icon" aria-hidden="true">&#9646;&#9646;</span> 一時停止';
  dom.btnPause().setAttribute('aria-label', '録音を一時停止する');
}

/**
 * MediaRecorder の stop イベントハンドラ
 * Blob を生成してメタデータと共に IndexedDB に保存する
 */
async function handleRecordingStop() {
  const mimeType = state.mediaRecorder.mimeType || 'audio/webm';
  const blob = new Blob(state.audioChunks, { type: mimeType });
  const durationMs = state.elapsedMs;
  const name = generateDefaultName();

  const record = {
    id: Date.now(),
    name,
    createdAt: new Date().toISOString(),
    durationMs,
    mimeType,
    blob,
  };

  try {
    await dbSave(record);
    const records = await dbGetAll();
    renderRecordingList(records);
  } catch (err) {
    console.error('IndexedDB 保存失敗:', err);
    showError('録音データの保存に失敗しました。ストレージの空き容量を確認してください。');
  }
}

/**
 * デフォルトの録音名を生成する（例: 録音_20260530_112030）
 * @returns {string}
 */
function generateDefaultName() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `録音_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

/**
 * サポートされている MimeType を返す
 * @returns {string|null}
 */
function getSupportedMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
  ];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return null;
}

/**
 * getUserMedia のエラーを日本語メッセージで処理する
 * @param {Error} err
 */
function handleGetUserMediaError(err) {
  if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
    showError('マイクの使用が許可されませんでした。ブラウザのアドレスバー左のアイコンから、マイクへのアクセスを許可してください。');
  } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
    showError('マイクが見つかりませんでした。マイクが接続されているか確認してください。');
  } else if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
    showError('マイクが他のアプリケーションで使用中です。他のアプリを閉じてから再度お試しください。');
  } else {
    showError(`マイクへのアクセスに失敗しました（${err.name}）。ブラウザの設定を確認してください。`);
  }
}

/* ===================================
   タイマー
   =================================== */

function startTimer() {
  state.timerIntervalId = setInterval(updateTimerDisplay, 100);
}

function stopTimer() {
  clearInterval(state.timerIntervalId);
  state.timerIntervalId = null;
}

function updateTimerDisplay() {
  const elapsed = state.elapsedMs + (state.timerStartedAt ? Date.now() - state.timerStartedAt : 0);
  dom.timer().textContent = formatTime(elapsed);
}

/**
 * ミリ秒を mm:ss 形式にフォーマットする
 * @param {number} ms
 * @returns {string}
 */
function formatTime(ms) {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/* ===================================
   リアルタイム波形可視化（AnalyserNode）
   =================================== */

/**
 * AudioContext + AnalyserNode をセットアップする
 * @param {MediaStream} stream
 */
function setupAnalyser(stream) {
  try {
    // webkitAudioContext は Safari の旧実装向けフォールバック
    const AudioCtx = window.AudioContext || /** @type {typeof AudioContext|undefined} */ (window['webkitAudioContext']);
    if (!AudioCtx) return;

    state.audioContext = new AudioCtx();
    state.analyser = state.audioContext.createAnalyser();
    state.analyser.fftSize = 256;
    state.analyser.smoothingTimeConstant = 0.8;

    state.sourceNode = state.audioContext.createMediaStreamSource(stream);
    state.sourceNode.connect(state.analyser);
    // analyser は destination に接続しない（スピーカーにフィードバックしない）
  } catch (err) {
    console.warn('AnalyserNode セットアップ失敗:', err);
  }
}

/**
 * requestAnimationFrame ループで波形を描画する
 */
function startVisualizer() {
  dom.visualizerHint().classList.add('hidden');

  const canvas = dom.visualizer();
  const ctx = canvas.getContext('2d');

  // canvas の描画サイズを実際の表示サイズに合わせる
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width || 600;
  canvas.height = rect.height || 120;

  function draw() {
    if (state.mode !== 'recording') return;
    state.animationFrameId = requestAnimationFrame(draw);

    if (!state.analyser) {
      drawFlatLine(ctx, canvas);
      return;
    }

    const bufferLength = state.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    state.analyser.getByteTimeDomainData(dataArray);

    drawWaveform(ctx, canvas, dataArray, bufferLength);
  }

  draw();
}

/**
 * 波形描画を停止し、ビジュアライザーをリセットする
 */
function stopVisualizer() {
  if (state.animationFrameId) {
    cancelAnimationFrame(state.animationFrameId);
    state.animationFrameId = null;
  }

  if (state.mode === 'idle') {
    // 録音終了（idle）ならキャンバス゘リアしてヒントを再表示
    const canvas = dom.visualizer();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    dom.visualizerHint().classList.remove('hidden');

    // AudioContext を閉じる
    if (state.audioContext) {
      state.audioContext.close().catch(() => {});
      state.audioContext = null;
      state.analyser = null;
      state.sourceNode = null;
    }
  }
}

/**
 * 波形（時間軸）を canvas に描画する
 * @param {CanvasRenderingContext2D} ctx
 * @param {HTMLCanvasElement} canvas
 * @param {Uint8Array} dataArray
 * @param {number} bufferLength
 */
function drawWaveform(ctx, canvas, dataArray, bufferLength) {
  const w = canvas.width;
  const h = canvas.height;

  // 背景クリア
  ctx.clearRect(0, 0, w, h);

  // ダークモード判定
  const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  ctx.strokeStyle = isDark ? '#60a5fa' : '#3b82f6';
  ctx.lineWidth = 2;
  ctx.beginPath();

  const sliceWidth = w / bufferLength;
  let x = 0;

  for (let i = 0; i < bufferLength; i++) {
    const v = dataArray[i] / 128.0; // 0〜2 の範囲に正規化
    const y = (v * h) / 2;

    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
    x += sliceWidth;
  }

  ctx.lineTo(w, h / 2);
  ctx.stroke();
}

/**
 * 無音時のフラットライン描画
 * @param {CanvasRenderingContext2D} ctx
 * @param {HTMLCanvasElement} canvas
 */
function drawFlatLine(ctx, canvas) {
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  // ダークモード判定（波形描画と同じ基準で色を揃える）
  const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  ctx.strokeStyle = isDark ? '#4b5563' : '#9ca3af';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, h / 2);
  ctx.lineTo(w, h / 2);
  ctx.stroke();
}

/* ===================================
   UI 状態更新
   =================================== */

/**
 * state.mode に応じてボタンの有効/無効・テキストを切り替える
 */
function updateUI() {
  const isIdle = state.mode === 'idle';
  const isRecording = state.mode === 'recording';

  dom.btnRecord().disabled = !isIdle;
  dom.btnPause().disabled = isIdle;
  dom.btnStop().disabled = isIdle;

  // 録音中インジケーター
  if (isRecording) {
    dom.recDot().classList.remove('hidden');
  } else {
    dom.recDot().classList.add('hidden');
  }

  // タイマーをリセット（idle 時）
  if (isIdle) {
    dom.timer().textContent = '00:00';
    dom.recordingStatus().textContent = '';
  }
}

/* ===================================
   IndexedDB 操作
   =================================== */

/**
 * IndexedDB を開いて接続を返す Promise
 * @returns {Promise<IDBDatabase>}
 */
function dbOpen() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
        store.createIndex('createdAt', 'createdAt', { unique: false });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

/**
 * 録音データを IndexedDB に保存する
 * @param {object} record  {id, name, createdAt, durationMs, mimeType, blob}
 */
async function dbSave(record) {
  const db = await dbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(record);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = (e) => { db.close(); reject(e.target.error); };
  });
}

/**
 * すべての録音を新しい順に取得する
 * @returns {Promise<object[]>}
 */
async function dbGetAll() {
  const db = await dbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => {
      db.close();
      // 新しい順（id は Date.now() なので降順）
      const sorted = req.result.sort((a, b) => b.id - a.id);
      resolve(sorted);
    };
    req.onerror = (e) => { db.close(); reject(e.target.error); };
  });
}

/**
 * 指定 id の録音を削除する
 * @param {number} id
 */
async function dbDelete(id) {
  const db = await dbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = (e) => { db.close(); reject(e.target.error); };
  });
}

/**
 * 指定 id の録音名を更新する
 * @param {number} id
 * @param {string} newName
 */
async function dbRename(id, newName) {
  const db = await dbOpen();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const getReq = store.get(id);
    getReq.onsuccess = () => {
      const record = getReq.result;
      if (record) {
        record.name = newName;
        store.put(record);
      }
    };
    tx.oncomplete = () => { db.close(); resolve(); };
    tx.onerror = (e) => { db.close(); reject(e.target.error); };
  });
}

/* ===================================
   録音リスト描画
   =================================== */

/**
 * 録音リスト全体を再描画する
 * @param {object[]} records
 */
function renderRecordingList(records) {
  const list = dom.recordingList();

  // 既存項目（テンプレートから生成したもの）をすべて削除
  const existingItems = list.querySelectorAll('.recording-item');
  existingItems.forEach(el => el.remove());

  // 件数更新
  const count = records.length;
  dom.recordingsCount().textContent = `${count} 件`;

  if (count === 0) {
    dom.emptyMessage().style.display = '';
    return;
  }

  dom.emptyMessage().style.display = 'none';

  records.forEach(record => {
    const item = createRecordingItem(record);
    list.appendChild(item);
  });
}

/**
 * 録音リスト項目 DOM を生成して返す
 * @param {object} record
 * @returns {HTMLElement}
 */
function createRecordingItem(record) {
  const tpl = dom.itemTemplate();
  const clone = tpl.content.cloneNode(true);
  const li = clone.querySelector('li');

  li.dataset.id = record.id;

  // 名前
  li.querySelector('.recording-name').textContent = record.name;

  // メタ情報
  li.querySelector('.recording-date').textContent = formatDate(record.createdAt);
  li.querySelector('.recording-duration').textContent = formatTime(record.durationMs);

  // オーディオプレーヤー
  const audio = li.querySelector('.recording-player');
  const blobUrl = URL.createObjectURL(record.blob);
  audio.src = blobUrl;

  // WebM ダウンロード
  const dlWebm = li.querySelector('.dl-webm');
  dlWebm.href = blobUrl;
  dlWebm.download = `${record.name}.webm`;

  // WAV ダウンロード（AudioContext デコード → PCM エンコード）
  const dlWav = li.querySelector('.dl-wav');
  setupWavDownload(dlWav, record);

  // 削除ボタン
  li.querySelector('.delete-btn').addEventListener('click', async () => {
    if (!window.confirm(`「${record.name}」を削除しますか？`)) return;
    URL.revokeObjectURL(blobUrl);
    await dbDelete(record.id);
    const records = await dbGetAll();
    renderRecordingList(records);
  });

  // リネームボタン
  const nameDisplay = li.querySelector('.name-display');
  const nameEdit = li.querySelector('.name-edit');
  const renameInput = li.querySelector('.rename-input');

  li.querySelector('.rename-btn').addEventListener('click', () => {
    nameDisplay.classList.add('hidden');
    nameEdit.classList.remove('hidden');
    renameInput.value = record.name;
    renameInput.focus();
    renameInput.select();
  });

  const commitRename = async () => {
    const newName = renameInput.value.trim();
    if (!newName) {
      renameInput.focus();
      return;
    }
    record.name = newName;
    li.querySelector('.recording-name').textContent = newName;
    dlWebm.download = `${newName}.webm`;
    nameEdit.classList.add('hidden');
    nameDisplay.classList.remove('hidden');
    await dbRename(record.id, newName);
  };

  li.querySelector('.rename-ok').addEventListener('click', commitRename);
  li.querySelector('.rename-cancel').addEventListener('click', () => {
    nameEdit.classList.add('hidden');
    nameDisplay.classList.remove('hidden');
  });
  renameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') commitRename();
    if (e.key === 'Escape') {
      nameEdit.classList.add('hidden');
      nameDisplay.classList.remove('hidden');
    }
  });

  return li;
}

/**
 * ISO 日時文字列を日本語表示にフォーマットする
 * @param {string} isoString
 * @returns {string}
 */
function formatDate(isoString) {
  const d = new Date(isoString);
  return d.toLocaleString('ja-JP', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

/* ===================================
   WAV 変換ダウンロード（加点機能）
   =================================== */

/**
 * Blob (WebM/Ogg) を WAV (RIFF PCM 16bit) に変換してダウンロードリンクを設定する
 * AudioContext.decodeAudioData → Float32Array → PCM → RIFF ヘッダー付与
 * @param {HTMLAnchorElement} link
 * @param {object} record
 */
function setupWavDownload(link, record) {
  link.textContent = '↓ WAV';
  link.href = '#';
  link.removeAttribute('download');

  let wavBlobUrl = null;

  link.addEventListener('click', async (e) => {
    e.preventDefault();

    // 変換済みならそのまま DL
    if (wavBlobUrl) {
      triggerDownload(wavBlobUrl, `${record.name}.wav`);
      return;
    }

    link.textContent = '変換中...';
    link.style.pointerEvents = 'none';

    try {
      // webkitAudioContext は Safari の旧実装向けフォールバック
      const AudioCtx = window.AudioContext || /** @type {typeof AudioContext|undefined} */ (window['webkitAudioContext']);
      if (!AudioCtx) throw new Error('Web Audio API 非対応');

      const arrayBuffer = await record.blob.arrayBuffer();
      const audioCtx = new AudioCtx();
      const decoded = await audioCtx.decodeAudioData(arrayBuffer);
      await audioCtx.close();

      const wavBuffer = encodeWav(decoded);
      const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });
      wavBlobUrl = URL.createObjectURL(wavBlob);

      triggerDownload(wavBlobUrl, `${record.name}.wav`);
      link.textContent = '↓ WAV';
      link.style.pointerEvents = '';
    } catch (err) {
      console.warn('WAV 変換失敗:', err);
      link.textContent = '↓ WAV (変換失敗)';
      link.style.pointerEvents = '';
    }
  });
}

/**
 * 一時的な <a> を生成してファイルをダウンロードさせる
 * @param {string} url
 * @param {string} filename
 */
function triggerDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * AudioBuffer を RIFF WAV フォーマット (PCM 16bit) に変換する
 * @param {AudioBuffer} audioBuffer
 * @returns {ArrayBuffer}
 */
function encodeWav(audioBuffer) {
  const numChannels = audioBuffer.numberOfChannels;
  const sampleRate = audioBuffer.sampleRate;
  const numSamples = audioBuffer.length;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;

  // PCM データを生成（全チャンネルのインターリーブ）
  const pcmData = new Int16Array(numSamples * numChannels);
  for (let ch = 0; ch < numChannels; ch++) {
    const channelData = audioBuffer.getChannelData(ch);
    for (let i = 0; i < numSamples; i++) {
      // Float32 [-1, 1] → Int16 [-32768, 32767]
      const sample = Math.max(-1, Math.min(1, channelData[i]));
      pcmData[i * numChannels + ch] = sample < 0
        ? Math.round(sample * 32768)
        : Math.round(sample * 32767);
    }
  }

  const dataSize = pcmData.byteLength;
  const headerSize = 44;
  const buffer = new ArrayBuffer(headerSize + dataSize);
  const view = new DataView(buffer);

  // RIFF チャンク
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');

  // fmt サブチャンク
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);                          // チャンクサイズ
  view.setUint16(20, 1, true);                           // PCM = 1
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numChannels * bytesPerSample, true); // バイトレート
  view.setUint16(32, numChannels * bytesPerSample, true); // ブロックアライン
  view.setUint16(34, bitsPerSample, true);

  // data サブチャンク
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // PCM データをコピー
  new Int16Array(buffer, headerSize).set(pcmData);

  return buffer;
}

/**
 * DataView の指定オフセットに ASCII 文字列を書き込む
 * @param {DataView} view
 * @param {number} offset
 * @param {string} str
 */
function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

/* ===================================
   初期化
   =================================== */

/**
 * アプリを初期化する
 */
async function init() {
  // ブラウザ対応チェック（非対応でも過去録音の閲覧は可能にする）
  const supported = checkBrowserSupport();

  // IndexedDB から過去の録音を復元（対応状況に関わらず実行）
  try {
    const records = await dbGetAll();
    renderRecordingList(records);
  } catch (err) {
    console.warn('録音リスト読み込み失敗:', err);
  }

  // 共通のイベントリスナー
  dom.errorClose().addEventListener('click', hideError);

  // 録音関連は対応ブラウザでのみ有効化（録音ボタンは checkBrowserSupport で無効化済み）
  if (supported) {
    // デバイスリストを読み込む（権限なしで呼ぶとラベルは空だが列挙は可能）
    await loadAudioDevices();

    dom.btnRecord().addEventListener('click', startRecording);
    dom.btnPause().addEventListener('click', togglePause);
    dom.btnStop().addEventListener('click', stopRecording);
    dom.refreshDevices().addEventListener('click', loadAudioDevices);
  }
}

// DOMContentLoaded 後に初期化
document.addEventListener('DOMContentLoaded', init);
