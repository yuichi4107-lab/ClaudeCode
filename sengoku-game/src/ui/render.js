import { provincesOf, totalTroops, areAllied } from '../engine/state.js';
import { goldIncome } from '../engine/economy.js';
import { GEO, GEO_LABEL, MAP_VIEWBOX } from '../data/geo.js';

const SEASONS = ['春', '夏', '秋', '冬'];
const SVGNS = 'http://www.w3.org/2000/svg';

export function renderTopbar(state) {
  document.getElementById('turn-label').textContent = `${state.year}年 ${SEASONS[state.season]}`;
  const p = state.daimyo[state.playerId];
  const provs = provincesOf(state, state.playerId).length;
  document.getElementById('player-stats').textContent =
    `${p.name}　金:${p.gold}　兵:${totalTroops(state, state.playerId)}　国:${provs}`;
}

export function renderMap(state, selectedId) {
  const svg = document.getElementById('map');
  svg.setAttribute('viewBox', MAP_VIEWBOX);
  svg.innerHTML = '';

  // 国の塗り分け（所有者色）。選択国は最後に描き直して枠を前面に出す
  for (const p of Object.values(state.provinces)) {
    const d = GEO[p.id];
    if (!d) { console.warn('geo path 欠落:', p.id); continue; }
    const path = document.createElementNS(SVGNS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', state.daimyo[p.owner].color);
    path.setAttribute('class', 'prov-fill' + (p.id === selectedId ? ' selected' : ''));
    path.setAttribute('data-prov', p.id);
    svg.appendChild(path);
  }

  // 国名ラベル
  for (const p of Object.values(state.provinces)) {
    const lab = GEO_LABEL[p.id];
    if (!lab) continue;
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('x', lab[0]);
    t.setAttribute('y', lab[1]);
    t.setAttribute('class', 'prov-label');
    t.textContent = p.name;
    svg.appendChild(t);
  }
}

function statRow(label, value) {
  return `<div class="stat"><span>${label}</span><span>${value}</span></div>`;
}

export function renderPanel(state, selectedId) {
  const panel = document.getElementById('side-panel');
  if (!selectedId) { panel.innerHTML = '<p>国を選択してください</p>'; return; }
  const p = state.provinces[selectedId];
  const owner = state.daimyo[p.owner];
  const isMine = p.owner === state.playerId;
  let html = `<h3>${p.name}（${p.region}）</h3>`;
  html += `<div style="color:${owner.color}">${owner.name}</div>`;
  html += statRow('石高', p.baseKokudaka) + statRow('兵力', p.troops)
    + statRow('農業', p.agri) + statRow('商業', p.commerce)
    + statRow('城防御', p.castle) + statRow('民忠', p.loyalty)
    + statRow('兵糧', p.rations) + statRow('地勢', p.terrain)
    + statRow('予想金収入', goldIncome(p));

  if (isMine) {
    html += `<div class="cmd-row">
      <button data-cmd="develop" data-kind="agri" data-prov="${p.id}">農業開発</button>
      <button data-cmd="develop" data-kind="commerce" data-prov="${p.id}">商業開発</button>
      <button data-cmd="recruit" data-prov="${p.id}">徴兵</button>
      <button data-cmd="train" data-prov="${p.id}">訓練</button>
    </div>`;
    // 出陣先（隣接する非同盟の敵国）
    const targets = p.neighbors
      .map(id => state.provinces[id])
      .filter(n => n && n.owner !== state.playerId && !areAllied(state, state.playerId, n.owner));
    if (targets.length) {
      html += '<div class="cmd-row">';
      for (const t of targets) {
        html += `<button data-cmd="attack" data-from="${p.id}" data-to="${t.id}">${t.name}へ出陣</button>`;
      }
      html += '</div>';
    }
  } else {
    html += `<div class="cmd-row">
      <button data-cmd="propose_alliance" data-to="${p.owner}">${owner.name}に同盟提案</button>
    </div>`;
  }
  panel.innerHTML = html;
}

export function renderLog(state) {
  const log = document.getElementById('log');
  const recent = state.log.slice(-40).reverse();
  log.innerHTML = recent.map(e => `<div class="entry">[${e.turn}] ${e.text}</div>`).join('');
}

export function renderRanking(state) {
  const rank = Object.values(state.daimyo)
    .filter(d => d.alive)
    .map(d => ({ name: d.name, color: d.color, n: provincesOf(state, d.id).length }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 12);
  document.getElementById('ranking').innerHTML =
    '<b>勢力ランキング</b>' + rank.map(r =>
      `<div class="stat"><span><span class="swatch" style="background:${r.color}"></span>${r.name}</span><span>${r.n}国</span></div>`
    ).join('');
}

export function render(state, selectedId) {
  renderTopbar(state);
  renderMap(state, selectedId);
  renderPanel(state, selectedId);
  renderLog(state);
  renderRanking(state);
}
