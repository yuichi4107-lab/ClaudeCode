export const SAVE_VERSION = 1;
const KEY = 'sengoku_save';

function storageOf(s) {
  return s ?? (typeof localStorage !== 'undefined' ? localStorage : null);
}

export function saveGame(state, s) {
  const store = storageOf(s);
  if (!store) return false;
  store.setItem(KEY, JSON.stringify({ version: SAVE_VERSION, state }));
  return true;
}

export function loadGame(s) {
  const store = storageOf(s);
  if (!store) return null;
  const raw = store.getItem(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed.version !== SAVE_VERSION) return null;
    return parsed.state;
  } catch {
    return null;
  }
}

export function hasSave(s) {
  const store = storageOf(s);
  return !!(store && store.getItem(KEY));
}
