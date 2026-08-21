import { SCENARIO_1560 } from './data/daimyo.js';
import { createInitialState } from './engine/state.js';
import { startSeason, endTurn, applyAction } from './engine/turn.js';
import { saveGame, loadGame } from './engine/save.js';
import { render } from './ui/render.js';
import { wireUI } from './ui/input.js';

export const APP_NAME = '戦国・国盗り';

const app = { game: null, selected: null };

function showModal(text) {
  document.getElementById('modal-text').textContent = text;
  document.getElementById('modal').hidden = false;
}
function hideModal() { document.getElementById('modal').hidden = true; }

function rerender() {
  if (!app.game) return;
  render(app.game, app.selected);
}

function checkEnd() {
  if (app.game.status === 'won') showModal('天下統一を成し遂げた！');
  else if (app.game.status === 'lost') showModal('我が家は滅亡した…');
}

function startGame(playerId) {
  app.game = createInitialState(SCENARIO_1560, playerId);
  app.selected = null;
  startSeason(app.game); // 初季の収入
  document.getElementById('start-screen').hidden = true;
  document.getElementById('game-screen').hidden = false;
  rerender();
}

function renderDaimyoPicker() {
  const picker = document.getElementById('daimyo-picker');
  picker.innerHTML = SCENARIO_1560.daimyo.map(d =>
    `<div class="daimyo-card" data-daimyo="${d.id}">
       <div><span class="swatch" style="background:${d.color}"></span><b>${d.name}</b></div>
       <div style="font-size:12px;opacity:.8">${d.family}</div>
       <div style="font-size:12px;opacity:.7">武${d.stats.valor}/政${d.stats.politics}/智${d.stats.intellect}</div>
     </div>`
  ).join('');
}

const handlers = {
  onPickDaimyo: (id) => startGame(id),

  onSelectProvince: (id) => { app.selected = id; rerender(); },

  onCommand: (btn) => {
    const cmd = btn.getAttribute('data-cmd');
    const pid = app.game.playerId;
    if (cmd === 'develop') {
      applyAction(app.game, pid, { type:'develop', province:btn.dataset.prov, kind:btn.dataset.kind });
    } else if (cmd === 'recruit') {
      applyAction(app.game, pid, { type:'recruit', province:btn.dataset.prov });
    } else if (cmd === 'train') {
      applyAction(app.game, pid, { type:'train', province:btn.dataset.prov });
    } else if (cmd === 'attack') {
      const to = btn.dataset.to;
      applyAction(app.game, pid, { type:'attack', from:btn.dataset.from, to,
        troops: app.game.provinces[btn.dataset.from].troops });
      // 攻略に成功していれば選択を移す
      if (app.game.provinces[to].owner === pid) app.selected = to;
    } else if (cmd === 'propose_alliance') {
      applyAction(app.game, pid, { type:'propose_alliance', to:btn.dataset.to });
    }
    rerender();
  },

  onEndTurn: () => {
    endTurn(app.game);
    rerender();
    checkEnd();
  },

  onSave: () => { if (saveGame(app.game)) flash('セーブしました'); },

  onLoad: () => {
    const loaded = loadGame();
    if (!loaded) { flash('セーブがありません'); return; }
    app.game = loaded; app.selected = null;
    document.getElementById('start-screen').hidden = true;
    document.getElementById('game-screen').hidden = false;
    rerender();
  },

  onModalOk: () => {
    hideModal();
    if (app.game && (app.game.status === 'won' || app.game.status === 'lost')) {
      // ゲーム終了 → 開始画面へ
      document.getElementById('game-screen').hidden = true;
      document.getElementById('start-screen').hidden = false;
    }
  },
};

function flash(text) {
  app.game.log.push({ turn: `${app.game.year}-${app.game.season}`, type:'info', text });
  rerender();
}

function boot() {
  renderDaimyoPicker();
  wireUI(handlers);
}

if (typeof document !== 'undefined') boot();
