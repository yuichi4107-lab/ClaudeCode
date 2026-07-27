"use strict";

/*
 * PDF書き込みツール - 工程1〜3（骨格・書き込みUI・保存）
 * pdf.jsは表示専用として使用する。書き込み機能（テキスト/ペン/蛍光ペン）は工程2で実装済み。
 * 保存機能（pdf-lib + fontkit + NotoSansCJKjp埋め込み、ページのコンテンツストリームへの直接描画）は
 * 工程3で実装。すべてのライブラリ・フォントは vendor/ からローカル読み込みし、CDN通信は行わない。
 */

// pdf.js worker をローカルファイルから読み込む（CDN依存ゼロ）
pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdf.worker.min.js";

// 注意: cMapUrl / standardFontDataUrl は pdf.worker.min.js 自身のスクリプト位置（vendor/配下）
// からの相対パスとして解決されるため、ここでは "vendor/" を含めない相対パスを指定する。
// （"./vendor/cmaps/" と書くと "vendor/vendor/cmaps/" に二重解決されてしまう）
const CMAP_URL = "./cmaps/";
const CMAP_PACKED = true;
const STANDARD_FONT_DATA_URL = "./standard_fonts/";

const state = {
  pdfDoc: null,
  currentPage: 1,
  pageCount: 0,
  zoom: 1.0,
  minZoom: 0.25,
  maxZoom: 4.0,
  fileName: "",
  renderTask: null,
  renderPending: null,
  // 保存（工程3）用に保持する元PDFのバイト列。pdf.jsのgetDocument({data})は
  // 渡したArrayBufferをWorkerへtransferしdetachしてしまうため、読み込み時に複製して保持する。
  originalPdfBytes: null,

  // ---- 工程2: 書き込みUI ----
  tool: "select", // "select" | "text" | "pen" | "highlighter"
  styles: {
    text: { size: 16, color: "#e02424" },
    pen: { color: "#e02424", width: 3 },
    highlighter: { color: "#ffe600", width: 16 },
  },
  selectedTextId: null,
  editingTextId: null,
  isDrawing: false,
  currentStroke: null,
  dragState: null, // { id, pointerId, startClientX, startClientY, startX, startY, moved }
  idCounter: 1,
  undoStack: [],
};

/*
 * 内部モデル（工程3のpdf-lib焼き込み処理が読み取る唯一のデータソース）
 * window.annotationModel = {
 *   [pageNo]: [
 *     { id, type: 'text', x, y, size, color, text },
 *     { id, type: 'ink' | 'highlight', color, width, points: [[x, y], ...] },
 *     ...
 *   ]
 * }
 *
 * 座標系（重要・工程3でも同じ規約を使うこと）:
 *   - x, y は「pdf.js の page.getViewport({ scale: 1.0 }) が返す座標系」そのもの。
 *   - 原点は左上 (0, 0)。x は右方向、y は下方向に増加する（スクリーン座標と同じ向き）。
 *   - この座標系は PDF ページの実ユーザー空間（1単位 = 1pt）と等しいスケールだが、
 *     Y軸の向きが逆（PDF標準は左下原点・Y上方向）。
 *     pdf-lib で描画する際は pdfY = pageHeightPt - modelY で変換すること。
 *   - フォントサイズ・線幅も同じスケール（pt相当）で保存する。ズーム倍率は描画時にのみ掛け算し、
 *     モデルには一切ズームの影響を持たせない。
 */
window.annotationModel = {};

const els = {
  btnOpen: document.getElementById("btn-open"),
  fileInput: document.getElementById("file-input"),
  fileName: document.getElementById("file-name"),
  dropZone: document.getElementById("drop-zone"),
  emptyState: document.getElementById("empty-state"),
  pageWrapper: document.getElementById("page-wrapper"),
  canvasStack: document.getElementById("canvas-stack"),
  canvas: document.getElementById("pdf-canvas"),
  annotationCanvas: document.getElementById("annotation-canvas"),
  annotationLayer: document.getElementById("annotation-layer"),
  toolGroup: document.getElementById("tool-group"),
  toolButtons: {
    select: document.getElementById("tool-select"),
    text: document.getElementById("tool-text"),
    pen: document.getElementById("tool-pen"),
    highlighter: document.getElementById("tool-highlighter"),
  },
  btnUndo: document.getElementById("btn-undo"),
  optionGroup: document.getElementById("option-group"),
  optFieldSize: document.getElementById("opt-field-size"),
  optFieldWidth: document.getElementById("opt-field-width"),
  optFieldColor: document.getElementById("opt-field-color"),
  optFontSize: document.getElementById("opt-font-size"),
  optLineWidth: document.getElementById("opt-line-width"),
  optColor: document.getElementById("opt-color"),
  btnDeleteSelected: document.getElementById("btn-delete-selected"),
  btnPrevPage: document.getElementById("btn-prev-page"),
  btnNextPage: document.getElementById("btn-next-page"),
  pageInput: document.getElementById("page-input"),
  pageCount: document.getElementById("page-count"),
  btnZoomOut: document.getElementById("btn-zoom-out"),
  btnZoomIn: document.getElementById("btn-zoom-in"),
  zoomLevel: document.getElementById("zoom-level"),
  btnSave: document.getElementById("btn-save"),
  statusMessage: document.getElementById("status-message"),
  viewerContainer: document.getElementById("viewer-container"),
};

function setStatus(message, isError) {
  els.statusMessage.textContent = message;
  els.statusMessage.classList.toggle("is-error", Boolean(isError));
  if (isError) {
    console.error("[pdf-annotator]", message);
  }
}

function setNavEnabled(enabled) {
  els.btnPrevPage.disabled = !enabled;
  els.btnNextPage.disabled = !enabled;
  els.pageInput.disabled = !enabled;
  els.btnZoomOut.disabled = !enabled;
  els.btnZoomIn.disabled = !enabled;
  els.btnSave.disabled = !enabled;
}

function setToolsEnabled(enabled) {
  Object.values(els.toolButtons).forEach((btn) => {
    btn.disabled = !enabled;
  });
  els.btnUndo.disabled = !enabled || state.undoStack.length === 0;
  if (!enabled) {
    els.optionGroup.hidden = true;
  }
}

async function loadPdfFromArrayBuffer(arrayBuffer, fileName) {
  try {
    setStatus("PDFを読み込み中...");

    // pdf.jsのgetDocument({data})に渡すArrayBufferはWorkerへtransferされ、その場でdetach
    // （byteLength 0）される。保存処理（工程3）では読み込み時の元バイト列がそのまま必要になるため、
    // pdf.jsに渡す前に独立したコピーを複製して保持しておく。
    state.originalPdfBytes = arrayBuffer.slice(0);

    const loadingTask = pdfjsLib.getDocument({
      data: arrayBuffer,
      cMapUrl: CMAP_URL,
      cMapPacked: CMAP_PACKED,
      standardFontDataUrl: STANDARD_FONT_DATA_URL,
    });
    const pdfDoc = await loadingTask.promise;

    state.pdfDoc = pdfDoc;
    state.pageCount = pdfDoc.numPages;
    state.currentPage = 1;
    state.zoom = 1.0;
    state.fileName = fileName;

    // 新規PDF読み込み時は書き込み内容・undo履歴・選択状態をリセットする
    window.annotationModel = {};
    state.undoStack = [];
    state.selectedTextId = null;
    state.editingTextId = null;
    setTool("select");

    els.fileName.textContent = fileName;
    els.pageCount.textContent = String(state.pageCount);
    els.pageInput.max = String(state.pageCount);
    els.pageInput.value = "1";

    els.emptyState.hidden = true;
    els.pageWrapper.hidden = false;

    setNavEnabled(true);
    setToolsEnabled(true);
    updateZoomLabel();

    await renderCurrentPage();
    setStatus(`${fileName} を読み込みました（全${state.pageCount}ページ）`);
  } catch (err) {
    setStatus(`PDFの読み込みに失敗しました: ${err && err.message ? err.message : err}`, true);
  }
}

async function renderCurrentPage() {
  if (!state.pdfDoc) return;

  // 連続でページ/ズームが変わった場合に前の描画とレースしないよう直列化する
  if (state.renderTask) {
    state.renderPending = renderCurrentPage;
    return;
  }

  state.renderTask = (async () => {
    try {
      const page = await state.pdfDoc.getPage(state.currentPage);
      const viewport = page.getViewport({ scale: state.zoom });

      const dpr = window.devicePixelRatio || 1;
      const canvas = els.canvas;
      const ctx = canvas.getContext("2d");

      // devicePixelRatio を考慮し、実ピクセルは高解像度・CSS表示サイズはCSSピクセルに保つ
      // これによりRetina/高DPI環境でも文字が滲まない
      canvas.width = Math.floor(viewport.width * dpr);
      canvas.height = Math.floor(viewport.height * dpr);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;

      // 注釈オーバーレイ（ストローク用canvas・テキスト用DOM層）もPDFキャンバスと同じ寸法に揃える
      els.annotationCanvas.width = canvas.width;
      els.annotationCanvas.height = canvas.height;
      els.annotationCanvas.style.width = canvas.style.width;
      els.annotationCanvas.style.height = canvas.style.height;

      els.annotationLayer.style.width = `${Math.floor(viewport.width)}px`;
      els.annotationLayer.style.height = `${Math.floor(viewport.height)}px`;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const renderContext = {
        canvasContext: ctx,
        viewport,
      };
      await page.render(renderContext).promise;

      els.pageInput.value = String(state.currentPage);
      refreshAnnotations();
    } catch (err) {
      setStatus(`ページの描画に失敗しました: ${err && err.message ? err.message : err}`, true);
    } finally {
      state.renderTask = null;
      if (state.renderPending) {
        const next = state.renderPending;
        state.renderPending = null;
        next();
      }
    }
  })();

  return state.renderTask;
}

function updateZoomLabel() {
  els.zoomLevel.textContent = `${Math.round(state.zoom * 100)}%`;
}

function goToPage(pageNumber) {
  if (!state.pdfDoc) return;
  const clamped = Math.min(Math.max(pageNumber, 1), state.pageCount);
  if (clamped === state.currentPage) return;
  // ページ切替前に編集中テキストを確定し、選択状態は次ページに持ち越さない
  commitEditingIfAny();
  state.selectedTextId = null;
  updateOptionGroupUI();
  state.currentPage = clamped;
  renderCurrentPage();
}

function setZoom(newZoom) {
  if (!state.pdfDoc) return;
  const clamped = Math.min(Math.max(newZoom, state.minZoom), state.maxZoom);
  if (clamped === state.zoom) return;
  commitEditingIfAny();
  state.zoom = clamped;
  updateZoomLabel();
  renderCurrentPage();
}

/* =========================================================================
 * 工程2: 書き込みUI（テキスト・ペン・蛍光ペン・undo）
 * 内部モデル window.annotationModel を唯一のデータソースとし、
 * 描画（Canvas: ペン/蛍光ペン、DOM: テキスト）はモデルから都度再構築する。
 * ========================================================================= */

function getPageAnnotations(pageNo) {
  if (!window.annotationModel[pageNo]) {
    window.annotationModel[pageNo] = [];
  }
  return window.annotationModel[pageNo];
}

function genId() {
  state.idCounter += 1;
  return `a${state.idCounter}`;
}

// クリック/ポインタ位置（クライアント座標）を内部モデル座標（scale=1.0のPDF座標系）に変換する
function clientToModel(clientX, clientY) {
  const rect = els.canvasStack.getBoundingClientRect();
  const cssX = clientX - rect.left;
  const cssY = clientY - rect.top;
  return { x: cssX / state.zoom, y: cssY / state.zoom };
}

// ---------- undo（スナップショット方式） ----------
// 変更「前」の状態を丸ごと退避しておき、undo時にページ単位で丸ごと復元する。
// 1回のテキスト追加・1本のストローク・1回のドラッグ移動・1回の編集セッションを1手として扱う。
function snapshotForUndo(pageNo) {
  const list = getPageAnnotations(pageNo);
  state.undoStack.push({ pageNo, prev: JSON.parse(JSON.stringify(list)) });
  if (state.undoStack.length > 100) state.undoStack.shift();
  els.btnUndo.disabled = false;
}

function performUndo() {
  const entry = state.undoStack.pop();
  if (!entry) return;
  window.annotationModel[entry.pageNo] = entry.prev;
  els.btnUndo.disabled = state.undoStack.length === 0;

  if (entry.pageNo === state.currentPage) {
    const stillExists = (id) => entry.prev.some((a) => a.id === id);
    if (state.selectedTextId && !stillExists(state.selectedTextId)) {
      state.selectedTextId = null;
    }
    if (state.editingTextId && !stillExists(state.editingTextId)) {
      state.editingTextId = null;
    }
    refreshAnnotations();
    updateOptionGroupUI();
  }
  setStatus("元に戻しました");
}

// ---------- 描画（ペン・蛍光ペン） ----------
function refreshAnnotations() {
  redrawStrokes();
  rebuildTextLayer();
}

function redrawStrokes() {
  const canvas = els.annotationCanvas;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const dpr = window.devicePixelRatio || 1;
  // モデル座標（scale=1.0）にdpr*zoomを掛けるだけで実ピクセルに変換されるようtransformを設定する。
  // これにより描画コードは常にモデル座標をそのまま使えばよい。
  ctx.setTransform(dpr * state.zoom, 0, 0, dpr * state.zoom, 0, 0);

  const list = getPageAnnotations(state.currentPage);
  for (const annot of list) {
    if (annot.type === "ink" || annot.type === "highlight") {
      drawStroke(ctx, annot);
    }
  }
}

function drawStroke(ctx, stroke) {
  if (!stroke.points || stroke.points.length === 0) return;
  ctx.save();
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = stroke.color;
  ctx.lineWidth = stroke.width;
  if (stroke.type === "highlight") {
    // 半透明・乗算合成で「下の文字が透けて見える」蛍光ペンらしい見た目にする
    ctx.globalCompositeOperation = "multiply";
    ctx.globalAlpha = 0.55;
  } else {
    ctx.globalAlpha = 1;
  }

  ctx.beginPath();
  if (stroke.points.length === 1) {
    const [x, y] = stroke.points[0];
    ctx.arc(x, y, stroke.width / 2, 0, Math.PI * 2);
    ctx.fillStyle = stroke.color;
    ctx.fill();
  } else {
    ctx.moveTo(stroke.points[0][0], stroke.points[0][1]);
    for (let i = 1; i < stroke.points.length - 1; i += 1) {
      const [cx, cy] = stroke.points[i];
      const [nx, ny] = stroke.points[i + 1];
      const mx = (cx + nx) / 2;
      const my = (cy + ny) / 2;
      ctx.quadraticCurveTo(cx, cy, mx, my);
    }
    const last = stroke.points[stroke.points.length - 1];
    ctx.lineTo(last[0], last[1]);
    ctx.stroke();
  }
  ctx.restore();
}

let strokeInProgress = null; // { pointerId }

function onCanvasPointerDown(e) {
  if (!state.pdfDoc) return;
  if (state.tool !== "pen" && state.tool !== "highlighter") return;
  if (e.button !== undefined && e.button !== 0) return;
  e.preventDefault();

  try {
    els.annotationCanvas.setPointerCapture(e.pointerId);
  } catch (err) {
    // Safari/一部環境や既にキャプチャ済みの場合に例外が出ることがあるが、
    // 描画自体はpointermove/upイベントで継続できるため致命的ではない
    console.warn("[pdf-annotator] setPointerCapture failed", err);
  }
  snapshotForUndo(state.currentPage);

  const style = state.tool === "pen" ? state.styles.pen : state.styles.highlighter;
  const pos = clientToModel(e.clientX, e.clientY);
  const stroke = {
    id: genId(),
    type: state.tool === "pen" ? "ink" : "highlight",
    color: style.color,
    width: style.width,
    points: [[pos.x, pos.y]],
  };
  getPageAnnotations(state.currentPage).push(stroke);
  state.isDrawing = true;
  state.currentStroke = stroke;
  strokeInProgress = { pointerId: e.pointerId };
  redrawStrokes();
}

function onCanvasPointerMove(e) {
  if (!state.isDrawing || !state.currentStroke) return;
  if (strokeInProgress && e.pointerId !== strokeInProgress.pointerId) return;
  const pos = clientToModel(e.clientX, e.clientY);
  state.currentStroke.points.push([pos.x, pos.y]);
  redrawStrokes();
}

function endStroke(e) {
  if (!state.isDrawing) return;
  state.isDrawing = false;
  state.currentStroke = null;
  strokeInProgress = null;
  if (e && e.pointerId !== undefined) {
    try {
      els.annotationCanvas.releasePointerCapture(e.pointerId);
    } catch (err) {
      /* すでに解放済みの場合は無視 */
    }
  }
}

// ---------- テキスト注釈 ----------
function rebuildTextLayer() {
  els.annotationLayer.innerHTML = "";
  const list = getPageAnnotations(state.currentPage);
  for (const annot of list) {
    if (annot.type !== "text") continue;
    els.annotationLayer.appendChild(createTextElement(annot));
  }
}

function createTextElement(annot) {
  const wrap = document.createElement("div");
  wrap.className = "text-annot";
  wrap.dataset.id = annot.id;
  wrap.style.left = `${annot.x * state.zoom}px`;
  wrap.style.top = `${annot.y * state.zoom}px`;

  const content = document.createElement("div");
  content.className = "text-annot-content";
  content.contentEditable = state.editingTextId === annot.id ? "true" : "false";
  content.textContent = annot.text;
  content.style.fontSize = `${annot.size * state.zoom}px`;
  content.style.color = annot.color;

  const del = document.createElement("button");
  del.type = "button";
  del.className = "text-annot-delete";
  del.textContent = "×";
  del.title = "削除";
  del.addEventListener("mousedown", (e) => e.stopPropagation());
  del.addEventListener("click", (e) => {
    e.stopPropagation();
    deleteText(annot.id);
  });

  wrap.appendChild(content);
  wrap.appendChild(del);

  if (state.selectedTextId === annot.id) wrap.classList.add("is-selected");
  if (state.editingTextId === annot.id) wrap.classList.add("is-editing");

  wrap.addEventListener("mousedown", (e) => onTextMouseDown(e, annot.id));

  return wrap;
}

function placeCaretAtEnd(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(false);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function focusTextContent(id) {
  const contentEl = els.annotationLayer.querySelector(`.text-annot[data-id="${id}"] .text-annot-content`);
  if (contentEl) {
    contentEl.focus();
    placeCaretAtEnd(contentEl);
  }
}

function createTextAnnotationAt(modelX, modelY) {
  // 追加＋その場での入力を1つのundo単位にするため、追加前の状態を退避する
  snapshotForUndo(state.currentPage);
  const style = state.styles.text;
  const annot = {
    id: genId(),
    type: "text",
    x: modelX,
    y: modelY,
    size: style.size,
    color: style.color,
    text: "",
  };
  getPageAnnotations(state.currentPage).push(annot);
  state.selectedTextId = annot.id;
  state.editingTextId = annot.id;
  rebuildTextLayer();
  updateOptionGroupUI();
  focusTextContent(annot.id);
}

// 編集中のテキストボックスの内容をモデルへ確定する。空文字なら注釈ごと破棄する。
// snapshotは編集セッション開始時（新規作成時 or 再クリック時）に取得済みのため、ここでは取らない。
function commitEditingIfAny() {
  if (!state.editingTextId) return;
  const id = state.editingTextId;
  state.editingTextId = null;
  const contentEl = els.annotationLayer.querySelector(`.text-annot[data-id="${id}"] .text-annot-content`);
  const list = getPageAnnotations(state.currentPage);
  const idx = list.findIndex((a) => a.id === id);
  if (idx === -1) return;
  const annot = list[idx];
  const newText = contentEl ? contentEl.innerText.replace(/\n+$/, "") : annot.text;

  if (newText.trim().length === 0) {
    list.splice(idx, 1);
    if (state.selectedTextId === id) state.selectedTextId = null;
  } else {
    annot.text = newText;
  }
}

function deleteText(id) {
  const list = getPageAnnotations(state.currentPage);
  const idx = list.findIndex((a) => a.id === id);
  if (idx === -1) return;
  snapshotForUndo(state.currentPage);
  list.splice(idx, 1);
  if (state.selectedTextId === id) state.selectedTextId = null;
  if (state.editingTextId === id) state.editingTextId = null;
  rebuildTextLayer();
  updateOptionGroupUI();
}

function onTextMouseDown(e, id) {
  if (state.editingTextId === id) {
    // 編集中のボックス自身のクリックはブラウザ標準のカーソル移動に任せる
    return;
  }
  e.preventDefault();
  e.stopPropagation();

  const list = getPageAnnotations(state.currentPage);
  const annot = list.find((a) => a.id === id);
  if (!annot) return;

  if (state.tool === "text") {
    commitEditingIfAny();
    snapshotForUndo(state.currentPage); // 既存テキストの再編集セッション開始
    state.selectedTextId = id;
    state.editingTextId = id;
    rebuildTextLayer();
    updateOptionGroupUI();
    focusTextContent(id);
    return;
  }

  if (state.tool !== "select") return;

  const wasSelected = state.selectedTextId === id;
  commitEditingIfAny();
  state.selectedTextId = id;
  updateOptionGroupUI();
  rebuildTextLayer();

  const startClientX = e.clientX;
  const startClientY = e.clientY;
  const startX = annot.x;
  const startY = annot.y;
  let moved = false;
  let snapshotTaken = false;

  function onMove(ev) {
    const distance = Math.hypot(ev.clientX - startClientX, ev.clientY - startClientY);
    if (!moved && distance < 3) return;
    if (!snapshotTaken) {
      snapshotForUndo(state.currentPage);
      snapshotTaken = true;
    }
    moved = true;
    annot.x = startX + (ev.clientX - startClientX) / state.zoom;
    annot.y = startY + (ev.clientY - startClientY) / state.zoom;
    rebuildTextLayer();
  }

  function onUp() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    if (!moved && wasSelected) {
      // 既に選択済みのテキストを再度クリック → 編集モードに入る
      snapshotForUndo(state.currentPage);
      state.editingTextId = id;
      rebuildTextLayer();
      updateOptionGroupUI();
      focusTextContent(id);
    }
  }

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

// ---------- ツール切替・オプションUI ----------
function setTool(tool) {
  if (state.tool === tool) return;
  commitEditingIfAny();
  state.tool = tool;
  if (tool !== "select") state.selectedTextId = null;

  Object.entries(els.toolButtons).forEach(([name, btn]) => {
    btn.classList.toggle("is-active", name === tool);
  });

  // 描画系ツールの間はテキスト層のポインタイベントを無効化し、逆にテキスト/選択ツールでは
  // 注釈canvas側を無効化して、意図しないレイヤーがクリックを奪わないようにする
  const drawMode = tool === "pen" || tool === "highlighter";
  els.annotationCanvas.style.pointerEvents = drawMode ? "auto" : "none";
  els.annotationLayer.style.pointerEvents = drawMode ? "none" : "auto";

  rebuildTextLayer();
  updateOptionGroupUI();
}

function updateOptionGroupUI() {
  const tool = state.tool;
  let selectedAnnot = null;
  if (tool === "select" && state.selectedTextId) {
    selectedAnnot = getPageAnnotations(state.currentPage).find((a) => a.id === state.selectedTextId);
  }

  if (tool === "text") {
    els.optionGroup.hidden = false;
    els.optFieldSize.hidden = false;
    els.optFieldColor.hidden = false;
    els.optFieldWidth.hidden = true;
    els.btnDeleteSelected.hidden = true;
    els.optFontSize.value = state.styles.text.size;
    els.optColor.value = state.styles.text.color;
  } else if (tool === "pen") {
    els.optionGroup.hidden = false;
    els.optFieldSize.hidden = true;
    els.optFieldColor.hidden = false;
    els.optFieldWidth.hidden = false;
    els.btnDeleteSelected.hidden = true;
    els.optLineWidth.value = state.styles.pen.width;
    els.optColor.value = state.styles.pen.color;
  } else if (tool === "highlighter") {
    els.optionGroup.hidden = false;
    els.optFieldSize.hidden = true;
    els.optFieldColor.hidden = false;
    els.optFieldWidth.hidden = false;
    els.btnDeleteSelected.hidden = true;
    els.optLineWidth.value = state.styles.highlighter.width;
    els.optColor.value = state.styles.highlighter.color;
  } else if (tool === "select" && selectedAnnot) {
    els.optionGroup.hidden = false;
    els.optFieldSize.hidden = false;
    els.optFieldColor.hidden = false;
    els.optFieldWidth.hidden = true;
    els.btnDeleteSelected.hidden = false;
    els.optFontSize.value = selectedAnnot.size;
    els.optColor.value = selectedAnnot.color;
  } else {
    els.optionGroup.hidden = true;
  }
}

function armSelectedAnnotSnapshot() {
  if (state.tool === "select" && state.selectedTextId) {
    snapshotForUndo(state.currentPage);
  }
}

function applyFontSizeChange() {
  const raw = parseInt(els.optFontSize.value, 10);
  const value = Number.isFinite(raw) ? Math.min(Math.max(raw, 10), 48) : state.styles.text.size;
  if (state.tool === "select" && state.selectedTextId) {
    const annot = getPageAnnotations(state.currentPage).find((a) => a.id === state.selectedTextId);
    if (annot) {
      annot.size = value;
      rebuildTextLayer();
    }
  } else {
    state.styles.text.size = value;
  }
}

function applyColorChange() {
  const value = els.optColor.value;
  if (state.tool === "select" && state.selectedTextId) {
    const annot = getPageAnnotations(state.currentPage).find((a) => a.id === state.selectedTextId);
    if (annot) {
      annot.color = value;
      rebuildTextLayer();
    }
  } else if (state.tool === "text") {
    state.styles.text.color = value;
  } else if (state.tool === "pen") {
    state.styles.pen.color = value;
  } else if (state.tool === "highlighter") {
    state.styles.highlighter.color = value;
  }
}

function applyLineWidthChange() {
  const raw = parseInt(els.optLineWidth.value, 10);
  const value = Number.isFinite(raw) ? Math.min(Math.max(raw, 1), 40) : 3;
  if (state.tool === "pen") {
    state.styles.pen.width = value;
  } else if (state.tool === "highlighter") {
    state.styles.highlighter.width = value;
  }
}

/* =========================================================================
 * 工程3: 保存（pdf-lib + fontkit による日本語フォント埋め込み・コンテンツストリーム直接描画）
 *
 * window.annotationModel を唯一のデータソースとして全ページを走査し、
 * pdf-libのPDFDocumentへ「注釈（Annotation）」としてではなく、各ページの
 * コンテンツストリームへ直接 drawText / drawSvgPath / drawCircle で焼き込む。
 *
 * 座標変換: モデル座標は page.getViewport({scale:1.0}) と同じ
 *   （原点左上・Y下方向、回転済みの見た目座標）。pdf-libの描画座標は
 *   ページの生のMediaBox基準（原点左下・Y上方向、回転前）のため、
 *   pdf.jsのviewport回転式の逆変換で変換する（modelToContentPoint）。
 *   rotate=0（無回転）は本ツールのテストPDFで実機検証済み。
 *   90/180/270度回転ページはpdf.jsのviewport変換式に基づき実装したが、
 *   回転PDFでの実機検証は未実施（README「既知の制限」参照）。
 * ========================================================================= */

let cachedJapaneseFontBytes = null;

// 保存に使う日本語フォント（NotoSansCJKjp-Regular.otf）をvendor/から取得する。
// index.html/app.js同様、fetch先はローカルファイルのみでCDN通信は発生しない。
async function fetchJapaneseFontBytes() {
  if (cachedJapaneseFontBytes) return cachedJapaneseFontBytes;
  const res = await fetch("./vendor/fonts/NotoSansCJKjp-Regular.otf");
  if (!res.ok) {
    throw new Error(`日本語フォントの読み込みに失敗しました (HTTP ${res.status})`);
  }
  cachedJapaneseFontBytes = await res.arrayBuffer();
  return cachedJapaneseFontBytes;
}

function hexToRgbColor(hex) {
  const clean = String(hex || "#000000").replace("#", "");
  const r = parseInt(clean.substring(0, 2), 16) / 255;
  const g = parseInt(clean.substring(2, 4), 16) / 255;
  const b = parseInt(clean.substring(4, 6), 16) / 255;
  return PDFLib.rgb(
    Number.isFinite(r) ? r : 0,
    Number.isFinite(g) ? g : 0,
    Number.isFinite(b) ? b : 0
  );
}

// pdf.jsのviewport回転式（display_utils.jsのgetViewport実装）の逆変換。
// モデル座標（回転後の見た目・原点左上Y下方向）→ pdf-libのページ内容座標
// （回転前のMediaBox基準・原点左下Y上方向）へ変換する。
function modelToContentPoint(modelX, modelY, pageWidth, pageHeight, rotationAngle) {
  const r = ((rotationAngle % 360) + 360) % 360;
  switch (r) {
    case 90:
      return { x: modelY, y: modelX };
    case 180:
      return { x: pageWidth - modelX, y: modelY };
    case 270:
      return { x: pageWidth - modelY, y: pageHeight - modelX };
    case 0:
    default:
      return { x: modelX, y: pageHeight - modelY };
  }
}

// テキストのx,yはCSS上の配置基準点（text-annot要素の左上角）。style.cssの
// .text-annot-content { padding: 2px 4px; line-height: 1.3; } と一致させるため、
// 同じpadding・line-heightでベースライン位置を計算し、画面表示とのズレを抑える。
const TEXT_ANNOT_PADDING_TOP = 2;
const TEXT_ANNOT_PADDING_LEFT = 4;
const TEXT_ANNOT_LINE_HEIGHT_RATIO = 1.3;

function drawTextAnnotation(page, font, fontMetrics, annot, pageWidth, pageHeight, rotationAngle) {
  const lineHeight = annot.size * TEXT_ANNOT_LINE_HEIGHT_RATIO;
  const ascentPt = (fontMetrics.ascent / fontMetrics.unitsPerEm) * annot.size;
  const descentAbsPt = (Math.abs(fontMetrics.descent) / fontMetrics.unitsPerEm) * annot.size;
  // CSSのhalf-leadingモデル: 行ボックス内の余白（line-height - 実文字高さ）を上下均等に配分し、
  // その半分 + フォントのascent分だけ行ボックス上端からベースラインが下がる
  const halfLeading = Math.max(0, (lineHeight - (ascentPt + descentAbsPt)) / 2);
  const baselineOffsetFromLineTop = halfLeading + ascentPt;

  const color = hexToRgbColor(annot.color);
  const lines = String(annot.text || "").split("\n");
  const rotateOpt = rotationAngle % 360 === 0 ? undefined : PDFLib.degrees(-rotationAngle);

  lines.forEach((line, i) => {
    if (line.length === 0) return; // 空行は描画するグリフがないためスキップ
    const modelX = annot.x + TEXT_ANNOT_PADDING_LEFT;
    const lineTopModelY = annot.y + TEXT_ANNOT_PADDING_TOP + i * lineHeight;
    const modelBaselineY = lineTopModelY + baselineOffsetFromLineTop;
    const { x, y } = modelToContentPoint(modelX, modelBaselineY, pageWidth, pageHeight, rotationAngle);
    page.drawText(line, {
      x,
      y,
      size: annot.size,
      font,
      color,
      rotate: rotateOpt,
    });
  });
}

// 画面表示のdrawStroke()（onCanvasPointerMove側のCanvas2D描画）と同じ二次ベジェ平滑化
// アルゴリズムでSVGパス文字列を組み立てる。見た目をできるだけ一致させるため。
//
// 注意（重要・実機検証で判明）: pdf-libのdrawSvgPath()は内部で独自にY軸を反転する
// 変換（"1 0 0 -1 0 0 cm"）を自動的に適用してからパス座標を描画する。
// 一方drawCircle()やdrawText()にはこの自動反転はない。
// 本関数へ渡すpointsはmodelToContentPoint()で既にPDFの内容座標系（原点左下・Y上方向）
// へ変換済みだが、drawSvgPathの自動反転と二重に反転してしまうと符号が反転し、
// ページ外（Y座標が負）に描画されて何も表示されなくなる不具合が実際に発生した
// （PyMuPDF/FreeTypeによる独立レンダリングで確認・修正済み）。
// そのため、drawSvgPathに渡す直前にのみYを再度反転（打ち消し）している。
function buildSvgPathFromPoints(points) {
  const p0 = negateYForSvgPath(points[0]);
  let d = `M ${p0.x} ${p0.y}`;
  for (let i = 1; i < points.length - 1; i += 1) {
    const c = negateYForSvgPath(points[i]);
    const n = points[i + 1];
    const m = negateYForSvgPath({ x: (points[i].x + n.x) / 2, y: (points[i].y + n.y) / 2 });
    d += ` Q ${c.x} ${c.y} ${m.x} ${m.y}`;
  }
  const last = negateYForSvgPath(points[points.length - 1]);
  d += ` L ${last.x} ${last.y}`;
  return d;
}

function negateYForSvgPath(point) {
  return { x: point.x, y: -point.y };
}

function drawStrokeAnnotation(page, annot, pageWidth, pageHeight, rotationAngle, isHighlight) {
  if (!annot.points || annot.points.length === 0) return;
  const contentPoints = annot.points.map(([mx, my]) =>
    modelToContentPoint(mx, my, pageWidth, pageHeight, rotationAngle)
  );
  const color = hexToRgbColor(annot.color);
  // 画面のmultiply合成+alpha0.55（style.css/app.jsのdrawStroke参照）相当の半透明表現。
  // pdf-lib側はExtGStateのBM(BlendMode)+opacityで近似する。
  const opacity = isHighlight ? 0.5 : 1;
  const blendMode = isHighlight ? PDFLib.BlendMode.Multiply : undefined;

  if (contentPoints.length === 1) {
    // drawCircleは自動Y反転がないため、modelToContentPointの結果をそのまま使う
    const { x, y } = contentPoints[0];
    page.drawCircle({
      x,
      y,
      size: annot.width / 2,
      color,
      opacity,
      blendMode,
    });
    return;
  }

  const path = buildSvgPathFromPoints(contentPoints);
  page.drawSvgPath(path, {
    x: 0,
    y: 0,
    borderColor: color,
    borderWidth: annot.width,
    borderOpacity: opacity,
    borderLineCap: PDFLib.LineCapStyle.Round,
    blendMode,
  });
}

async function buildAnnotatedPdfBytes() {
  if (!state.originalPdfBytes) {
    throw new Error("元PDFのデータが見つかりません。もう一度PDFを開き直してください。");
  }

  const fontBytes = await fetchJapaneseFontBytes();

  // ベースライン計算用のフォントメトリクス（ascent/descent/unitsPerEm）はfontkitの公開APIで
  // 直接取得する。pdf-lib内部のembedder実装に依存しないようにするため。
  const metricsFont = fontkit.create(new Uint8Array(fontBytes.slice(0)));
  const fontMetrics = {
    unitsPerEm: metricsFont.unitsPerEm,
    ascent: metricsFont.ascent,
    descent: metricsFont.descent,
  };

  const pdfDoc = await PDFLib.PDFDocument.load(state.originalPdfBytes.slice(0));
  pdfDoc.registerFontkit(fontkit);

  let jpFont;
  let usedSubset = true;
  try {
    // サブセット化（subset:true）でファイルサイズ肥大を防ぐのが既定方針。
    jpFont = await pdfDoc.embedFont(fontBytes.slice(0), { subset: true });
  } catch (err) {
    // 採用方式フォールバック: 一部のCJKグリフ構成でサブセット化に失敗するケースがあるため、
    // その場合はサブセットなしで再試行する（ファイルサイズは増えるが確実性を優先）。
    console.warn("[pdf-annotator] フォントのサブセット埋め込みに失敗。subset:falseで再試行します。", err);
    usedSubset = false;
    jpFont = await pdfDoc.embedFont(fontBytes.slice(0), { subset: false });
  }
  console.log(`[pdf-annotator] 日本語フォント埋め込み方式: ${usedSubset ? "subset:true" : "subset:false（フォールバック）"}`);

  const pages = pdfDoc.getPages();
  for (let i = 0; i < pages.length; i += 1) {
    const pageNo = i + 1;
    const annots = window.annotationModel[pageNo];
    if (!annots || annots.length === 0) continue; // 書き込みのないページは元内容のまま何もしない

    const page = pages[i];
    const pageWidth = page.getWidth();
    const pageHeight = page.getHeight();
    const rotationAngle = page.getRotation().angle || 0;

    for (const annot of annots) {
      if (annot.type === "text") {
        drawTextAnnotation(page, jpFont, fontMetrics, annot, pageWidth, pageHeight, rotationAngle);
      } else if (annot.type === "ink") {
        drawStrokeAnnotation(page, annot, pageWidth, pageHeight, rotationAngle, false);
      } else if (annot.type === "highlight") {
        drawStrokeAnnotation(page, annot, pageWidth, pageHeight, rotationAngle, true);
      }
    }
  }

  return pdfDoc.save();
}

function buildOutputFileName(originalName) {
  const base = originalName && originalName.trim().length > 0 ? originalName.trim() : "document.pdf";
  const withoutExt = base.toLowerCase().endsWith(".pdf") ? base.slice(0, base.length - 4) : base;
  return `annotated_${withoutExt}.pdf`;
}

function downloadBytes(bytes, fileName) {
  const blob = new Blob([bytes], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function setSaveUiBusy(busy) {
  els.btnSave.disabled = busy || !state.pdfDoc;
  els.btnSave.textContent = busy ? "保存中…" : "保存";
}

async function handleSave() {
  if (!state.pdfDoc) return;
  // 保存直前に編集中のテキストボックスを確定させ、最新の内容を反映する
  commitEditingIfAny();
  rebuildTextLayer();
  updateOptionGroupUI();

  setSaveUiBusy(true);
  try {
    setStatus("PDFを保存しています...");
    const bytes = await buildAnnotatedPdfBytes();
    downloadBytes(bytes, buildOutputFileName(state.fileName));
    setStatus("PDFを保存しました");
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    console.error("[pdf-annotator] 保存に失敗しました", err);
    setStatus(`PDFの保存に失敗しました: ${message}`, true);
    alert(`PDFの保存に失敗しました。\n${message}`);
  } finally {
    setSaveUiBusy(false);
  }
}

// ---------- イベント ----------

els.btnOpen.addEventListener("click", () => {
  els.fileInput.click();
});

els.fileInput.addEventListener("change", async (event) => {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    setStatus("PDFファイルを選択してください", true);
    return;
  }
  const arrayBuffer = await file.arrayBuffer();
  await loadPdfFromArrayBuffer(arrayBuffer, file.name);
  els.fileInput.value = "";
});

els.dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
  els.dropZone.classList.add("is-dragover");
});

els.dropZone.addEventListener("dragleave", (event) => {
  if (event.target === els.dropZone) {
    els.dropZone.classList.remove("is-dragover");
  }
});

els.dropZone.addEventListener("drop", async (event) => {
  event.preventDefault();
  els.dropZone.classList.remove("is-dragover");
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    setStatus("PDFファイルをドロップしてください", true);
    return;
  }
  const arrayBuffer = await file.arrayBuffer();
  await loadPdfFromArrayBuffer(arrayBuffer, file.name);
});

els.btnPrevPage.addEventListener("click", () => goToPage(state.currentPage - 1));
els.btnNextPage.addEventListener("click", () => goToPage(state.currentPage + 1));

els.pageInput.addEventListener("change", () => {
  const value = parseInt(els.pageInput.value, 10);
  if (Number.isNaN(value)) {
    els.pageInput.value = String(state.currentPage);
    return;
  }
  goToPage(value);
});

els.btnZoomIn.addEventListener("click", () => setZoom(state.zoom + 0.1));
els.btnZoomOut.addEventListener("click", () => setZoom(state.zoom - 0.1));

// ---------- 工程3: 保存のイベント ----------
els.btnSave.addEventListener("click", handleSave);

// ---------- 工程2: 書き込みUIのイベント ----------

Object.entries(els.toolButtons).forEach(([name, btn]) => {
  btn.addEventListener("click", () => setTool(name));
});

els.btnUndo.addEventListener("click", performUndo);
els.btnDeleteSelected.addEventListener("click", () => {
  if (state.selectedTextId) deleteText(state.selectedTextId);
});

els.optFontSize.addEventListener("input", applyFontSizeChange);
els.optFontSize.addEventListener("focus", armSelectedAnnotSnapshot);
els.optColor.addEventListener("input", applyColorChange);
els.optColor.addEventListener("focus", armSelectedAnnotSnapshot);
els.optLineWidth.addEventListener("input", applyLineWidthChange);

// ペン・蛍光ペンの描画（Pointer Eventsでマウス/タッチ/ペンを統一的に扱う）
els.annotationCanvas.addEventListener("pointerdown", onCanvasPointerDown);
els.annotationCanvas.addEventListener("pointermove", onCanvasPointerMove);
els.annotationCanvas.addEventListener("pointerup", endStroke);
els.annotationCanvas.addEventListener("pointercancel", endStroke);

// テキスト層の背景クリック: テキストツールなら新規作成、選択ツールなら選択解除
els.annotationLayer.addEventListener("mousedown", (e) => {
  if (e.target !== els.annotationLayer) return;
  if (!state.pdfDoc) return;
  if (state.tool === "text") {
    commitEditingIfAny();
    const pos = clientToModel(e.clientX, e.clientY);
    createTextAnnotationAt(pos.x, pos.y);
  } else if (state.tool === "select") {
    commitEditingIfAny();
    if (state.selectedTextId) {
      state.selectedTextId = null;
      rebuildTextLayer();
      updateOptionGroupUI();
    }
  }
});

// Delete/Backspaceで選択中テキストを削除、Ctrl+Z（Cmd+Z）でundo
document.addEventListener("keydown", (e) => {
  const active = document.activeElement;
  const isTypingContext =
    active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);

  if ((e.key === "Delete" || e.key === "Backspace") && !isTypingContext) {
    if (state.tool === "select" && state.selectedTextId && state.pdfDoc) {
      e.preventDefault();
      deleteText(state.selectedTextId);
    }
    return;
  }

  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "z") {
    if (!isTypingContext && state.pdfDoc) {
      e.preventDefault();
      performUndo();
    }
  }
});

// 初期状態
setNavEnabled(false);
setToolsEnabled(false);
updateZoomLabel();
updateOptionGroupUI();
