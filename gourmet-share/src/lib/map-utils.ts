import { GENRE_COLORS, type Genre } from './constants';

/**
 * ジャンルに応じた色付きピンのSVGアイコンを生成
 */
export function createGenreIcon(genre: Genre) {
  const color = GENRE_COLORS[genre] || '#546E7A';
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">
      <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.27 21.73 0 14 0z"
            fill="${color}" stroke="#fff" stroke-width="1.5"/>
      <circle cx="14" cy="14" r="6" fill="#fff"/>
    </svg>
  `;
  return svg;
}

/**
 * Leaflet用のDivIconを生成するためのHTML
 */
export function getMarkerIconHtml(genre: Genre): string {
  return createGenreIcon(genre);
}

/**
 * デフォルトの地図中心座標（東京駅）
 */
export const DEFAULT_CENTER: [number, number] = [35.6812, 139.7671];

/**
 * デフォルトのズーユレベル
 */
export const DEFAULT_ZOOM = 13;
