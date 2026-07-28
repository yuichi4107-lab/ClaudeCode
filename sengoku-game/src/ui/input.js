// handlers: {
//   onSelectProvince(id), onCommand(cmdEl), onEndTurn(),
//   onSave(), onLoad(), onPickDaimyo(id), onModalOk()
// }
export function wireUI(handlers) {
  // 地図クリック（ノード選択）
  document.getElementById('map').addEventListener('click', (e) => {
    const node = e.target.closest('[data-prov]');
    if (node) handlers.onSelectProvince(node.getAttribute('data-prov'));
  });

  // サイドパネルのコマンドボタン（委譲）
  document.getElementById('side-panel').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cmd]');
    if (btn) handlers.onCommand(btn);
  });

  // 開始画面の大名選択
  document.getElementById('daimyo-picker').addEventListener('click', (e) => {
    const card = e.target.closest('[data-daimyo]');
    if (card) handlers.onPickDaimyo(card.getAttribute('data-daimyo'));
  });

  document.getElementById('btn-end-turn').addEventListener('click', () => handlers.onEndTurn());
  document.getElementById('btn-save').addEventListener('click', () => handlers.onSave());
  document.getElementById('btn-load').addEventListener('click', () => handlers.onLoad());
  document.getElementById('modal-ok').addEventListener('click', () => handlers.onModalOk());
}
