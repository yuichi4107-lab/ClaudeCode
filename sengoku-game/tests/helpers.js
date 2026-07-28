// 3国2大名の小世界。エンジン純粋関数のテスト専用（史実データには依存しない）。
export function makeTestScenario() {
  return {
    year: 1560,
    season: 0,
    playerId: 'd1',
    provinces: [
      { id:'a', name:'A', region:'X', x:0.30, y:0.30, neighbors:['b'],
        terrain:'plain', baseKokudaka:50,
        owner:'d1', agri:40, commerce:40, troops:3000, castle:20, loyalty:70, rations:5000 },
      { id:'b', name:'B', region:'X', x:0.50, y:0.40, neighbors:['a','c'],
        terrain:'plain', baseKokudaka:40,
        owner:'d2', agri:30, commerce:30, troops:1500, castle:15, loyalty:60, rations:3000 },
      { id:'c', name:'C', region:'X', x:0.70, y:0.50, neighbors:['b'],
        terrain:'mountain', baseKokudaka:30,
        owner:'d2', agri:30, commerce:30, troops:2000, castle:25, loyalty:65, rations:4000 },
    ],
    daimyo: [
      { id:'d1', name:'D1', family:'D1家', color:'#cc3333', isPlayer:false, capital:'a',
        stats:{ valor:80, politics:70, intellect:75 }, gold:2000, alive:true, aiPersonality:'balanced' },
      { id:'d2', name:'D2', family:'D2家', color:'#3366cc', isPlayer:false, capital:'c',
        stats:{ valor:60, politics:50, intellect:55 }, gold:1500, alive:true, aiPersonality:'aggressive' },
    ],
  };
}

// 決定的な乱数源（テスト用）
export const fixed = (v) => () => v;          // 常に v
export const seq = (arr) => {                  // 順に返し、尽きたら最後を反復
  let i = 0;
  return () => arr[Math.min(i++, arr.length - 1)];
};
