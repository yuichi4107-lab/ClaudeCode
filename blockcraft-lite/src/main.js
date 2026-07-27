import * as THREE from 'three';
import { PointerLockControls } from 'three/addons/controls/PointerLockControls.js';
import {
  BLOCKS,
  HOTBAR,
  SAVE_KEY,
  blockKey,
  createWorld,
  deserializeWorld,
  getSpawn,
  isInsideBuildBounds,
  parseBlockKey,
  serializeWorld
} from './world.js';

const canvas = document.getElementById('scene');
const intro = document.getElementById('intro');
const playButton = document.getElementById('play-button');
const hotbar = document.getElementById('hotbar');
const message = document.getElementById('message');
const positionLabel = document.getElementById('position-label');

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x9ec9ff);
scene.fog = new THREE.Fog(0x9ec9ff, 36, 78);

const camera = new THREE.PerspectiveCamera(72, window.innerWidth / window.innerHeight, 0.1, 180);
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  powerPreference: 'high-performance',
  preserveDrawingBuffer: true
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const controls = new PointerLockControls(camera, document.body);
const raycaster = new THREE.Raycaster();
raycaster.far = 6;

const blockGroup = new THREE.Group();
scene.add(blockGroup);

const app = {
  world: createWorld(),
  selected: 'grass',
  meshes: [],
  velocityY: 0,
  grounded: false,
  lastTime: performance.now(),
  keys: new Set(),
  dirty: true
};

const PLAYER_RADIUS = 0.34;
const PLAYER_HEIGHT = 1.78;
const EYE_HEIGHT = 1.62;
const MOVE_SPEED = 6.3;
const JUMP_SPEED = 7.8;
const GRAVITY = 22;

const materials = Object.fromEntries(Object.values(BLOCKS).map(block => [block.id, createBlockMaterial(block)]));
const unitBox = new THREE.BoxGeometry(1, 1, 1);
const highlight = createHighlight();

setupScene();
buildHotbar();
loadInitialWorld();
rebuildMeshes();
bindEvents();
animate();

function setupScene() {
  scene.add(new THREE.HemisphereLight(0xddefff, 0x3d3325, 1.9));

  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(18, 32, 12);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.camera.left = -38;
  sun.shadow.camera.right = 38;
  sun.shadow.camera.top = 38;
  sun.shadow.camera.bottom = -38;
  scene.add(sun);

  const skyFloor = new THREE.Mesh(
    new THREE.PlaneGeometry(180, 180),
    new THREE.MeshLambertMaterial({ color: 0x5c8e42 })
  );
  skyFloor.rotation.x = -Math.PI / 2;
  skyFloor.position.y = -0.54;
  skyFloor.receiveShadow = true;
  scene.add(skyFloor);

  scene.add(highlight);
}

function createBlockMaterial(block) {
  const canvasTexture = document.createElement('canvas');
  canvasTexture.width = 64;
  canvasTexture.height = 64;
  const ctx = canvasTexture.getContext('2d');
  ctx.fillStyle = block.color;
  ctx.fillRect(0, 0, 64, 64);

  const shade = block.id === 'water' ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.11)';
  ctx.fillStyle = shade;
  for (let i = 0; i < 90; i += 1) {
    const x = Math.floor(Math.random() * 64);
    const y = Math.floor(Math.random() * 64);
    const size = 1 + Math.floor(Math.random() * 4);
    ctx.fillRect(x, y, size, size);
  }

  if (block.id === 'grass') {
    ctx.fillStyle = '#7cc553';
    ctx.fillRect(0, 0, 64, 14);
  } else if (block.id === 'wood') {
    ctx.fillStyle = 'rgba(58, 35, 16, 0.22)';
    for (let x = 9; x < 64; x += 15) ctx.fillRect(x, 0, 3, 64);
  } else if (block.id === 'water') {
    ctx.strokeStyle = 'rgba(255,255,255,0.35)';
    ctx.lineWidth = 3;
    for (let y = 13; y < 64; y += 18) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.bezierCurveTo(18, y - 8, 34, y + 8, 64, y);
      ctx.stroke();
    }
  }

  const texture = new THREE.CanvasTexture(canvasTexture);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;

  return new THREE.MeshLambertMaterial({
    map: texture,
    transparent: block.id === 'water',
    opacity: block.id === 'water' ? 0.72 : 1
  });
}

function createHighlight() {
  const edges = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.018, 1.018, 1.018));
  const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0xffffff, linewidth: 2 }));
  line.visible = false;
  return line;
}

function buildHotbar() {
  hotbar.innerHTML = HOTBAR.map((id, index) => {
    const block = BLOCKS[id];
    return `<button class="slot" type="button" data-block="${id}" title="${block.name}">
      <kbd>${index + 1}</kbd>
      <span class="block-preview" style="background:${block.color}"></span>
      <small>${block.name}</small>
    </button>`;
  }).join('');
  updateHotbar();
}

function updateHotbar() {
  for (const slot of hotbar.querySelectorAll('.slot')) {
    slot.classList.toggle('is-selected', slot.dataset.block === app.selected);
  }
}

function loadInitialWorld() {
  const saved = localStorage.getItem(SAVE_KEY);
  if (!saved) {
    setSpawn();
    return;
  }

  try {
    const data = deserializeWorld(saved);
    app.world = data.world;
    const spawn = data.player?.position || getSpawn(app.world);
    camera.position.set(spawn.x, spawn.y, spawn.z);
    app.selected = data.player?.selected && BLOCKS[data.player.selected] ? data.player.selected : app.selected;
    updateHotbar();
    setMessage('保存済みワールドを読み込みました');
  } catch {
    setSpawn();
    setMessage('保存データを読み込めませんでした');
  }
}

function setSpawn() {
  const spawn = getSpawn(app.world);
  camera.position.set(spawn.x, spawn.y, spawn.z);
}

function rebuildMeshes() {
  for (const mesh of app.meshes) {
    blockGroup.remove(mesh);
    mesh.geometry.dispose();
  }
  app.meshes = [];

  const byType = new Map();
  for (const [key, type] of Object.entries(app.world.blocks)) {
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type).push(parseBlockKey(key));
  }

  const matrix = new THREE.Matrix4();
  for (const [type, positions] of byType.entries()) {
    const mesh = new THREE.InstancedMesh(unitBox.clone(), materials[type], positions.length);
    mesh.castShadow = BLOCKS[type].solid;
    mesh.receiveShadow = true;
    mesh.userData.type = type;
    mesh.userData.positions = positions;

    positions.forEach(([x, y, z], index) => {
      matrix.makeTranslation(x, y, z);
      mesh.setMatrixAt(index, matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
    blockGroup.add(mesh);
    app.meshes.push(mesh);
  }
}

function bindEvents() {
  playButton.addEventListener('click', () => controls.lock());
  document.addEventListener('click', () => {
    if (!controls.isLocked && intro.hidden) controls.lock();
  });

  controls.addEventListener('lock', () => {
    intro.hidden = true;
    setMessage('探索中');
  });
  controls.addEventListener('unlock', () => {
    intro.hidden = false;
    setMessage('クリックで視点操作');
  });
  document.addEventListener('pointerlockerror', () => {
    setMessage('このブラウザでは視点ロックを開始できませんでした');
  });

  document.addEventListener('keydown', event => {
    app.keys.add(event.code);
    if (event.code === 'Space' && app.grounded) {
      app.velocityY = JUMP_SPEED;
      app.grounded = false;
    }

    const number = Number(event.key);
    if (number >= 1 && number <= HOTBAR.length) {
      app.selected = HOTBAR[number - 1];
      updateHotbar();
    }
  });

  document.addEventListener('keyup', event => app.keys.delete(event.code));
  document.addEventListener('contextmenu', event => event.preventDefault());

  document.addEventListener('mousedown', event => {
    if (!controls.isLocked) return;
    if (event.button === 0) breakTargetBlock();
    if (event.button === 2) placeTargetBlock();
  });

  hotbar.addEventListener('click', event => {
    const slot = event.target.closest('.slot');
    if (!slot) return;
    app.selected = slot.dataset.block;
    updateHotbar();
  });

  document.getElementById('save-button').addEventListener('click', saveWorld);
  document.getElementById('load-button').addEventListener('click', loadWorld);
  document.getElementById('reset-button').addEventListener('click', resetWorld);

  window.addEventListener('resize', resizeRenderer);
}

function animate(now = performance.now()) {
  const dt = Math.min(0.05, (now - app.lastTime) / 1000);
  app.lastTime = now;

  if (controls.isLocked) updatePlayer(dt);
  updateTargetHighlight();
  updatePositionLabel();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

function updatePlayer(dt) {
  const forward = Number(app.keys.has('KeyW')) - Number(app.keys.has('KeyS'));
  const right = Number(app.keys.has('KeyD')) - Number(app.keys.has('KeyA'));
  const scale = forward && right ? Math.SQRT1_2 : 1;

  moveHorizontal('forward', forward * MOVE_SPEED * scale * dt);
  moveHorizontal('right', right * MOVE_SPEED * scale * dt);

  app.velocityY -= GRAVITY * dt;
  moveVertical(app.velocityY * dt);

  if (camera.position.y < -12) {
    setSpawn();
    app.velocityY = 0;
    setMessage('スタート地点へ戻しました');
  }
}

function moveHorizontal(direction, distance) {
  if (!distance) return;
  const previous = camera.position.clone();
  if (direction === 'forward') controls.moveForward(distance);
  else controls.moveRight(distance);

  if (collidesWithWorld(camera.position)) {
    camera.position.copy(previous);
  }
}

function moveVertical(distance) {
  if (!distance) return;
  const previousY = camera.position.y;
  camera.position.y += distance;

  if (!collidesWithWorld(camera.position)) {
    app.grounded = false;
    return;
  }

  camera.position.y = previousY;
  if (distance < 0) app.grounded = true;
  app.velocityY = 0;
}

function collidesWithWorld(position) {
  const box = playerBox(position);
  const minX = Math.floor(box.minX - 0.5);
  const maxX = Math.ceil(box.maxX + 0.5);
  const minY = Math.floor(box.minY - 0.5);
  const maxY = Math.ceil(box.maxY + 0.5);
  const minZ = Math.floor(box.minZ - 0.5);
  const maxZ = Math.ceil(box.maxZ + 0.5);

  for (let x = minX; x <= maxX; x += 1) {
    for (let y = minY; y <= maxY; y += 1) {
      for (let z = minZ; z <= maxZ; z += 1) {
        const type = app.world.blocks[blockKey(x, y, z)];
        if (BLOCKS[type]?.solid && boxIntersectsBlock(box, x, y, z)) return true;
      }
    }
  }
  return false;
}

function playerBox(position) {
  return {
    minX: position.x - PLAYER_RADIUS,
    maxX: position.x + PLAYER_RADIUS,
    minY: position.y - EYE_HEIGHT,
    maxY: position.y - EYE_HEIGHT + PLAYER_HEIGHT,
    minZ: position.z - PLAYER_RADIUS,
    maxZ: position.z + PLAYER_RADIUS
  };
}

function boxIntersectsBlock(box, x, y, z) {
  return (
    box.maxX > x - 0.5 &&
    box.minX < x + 0.5 &&
    box.maxY > y - 0.5 &&
    box.minY < y + 0.5 &&
    box.maxZ > z - 0.5 &&
    box.minZ < z + 0.5
  );
}

function getTarget() {
  raycaster.setFromCamera({ x: 0, y: 0 }, camera);
  const hits = raycaster.intersectObjects(app.meshes, false);
  if (!hits.length) return null;

  const hit = hits[0];
  const position = hit.object.userData.positions[hit.instanceId];
  if (!position) return null;

  return {
    key: blockKey(position[0], position[1], position[2]),
    position,
    normal: hit.face.normal.clone()
  };
}

function updateTargetHighlight() {
  const target = getTarget();
  if (!target) {
    highlight.visible = false;
    return;
  }
  highlight.position.set(...target.position);
  highlight.visible = true;
}

function breakTargetBlock() {
  const target = getTarget();
  if (!target) return;
  const type = app.world.blocks[target.key];
  if (!type || type === 'water') {
    setMessage('水はそのまま残しました');
    return;
  }
  delete app.world.blocks[target.key];
  rebuildMeshes();
  setMessage(`${BLOCKS[type].name}を壊しました`);
}

function placeTargetBlock() {
  const target = getTarget();
  if (!target) return;

  const [x, y, z] = target.position;
  const nx = x + Math.round(target.normal.x);
  const ny = y + Math.round(target.normal.y);
  const nz = z + Math.round(target.normal.z);
  const key = blockKey(nx, ny, nz);

  if (!isInsideBuildBounds(nx, ny, nz)) {
    setMessage('そこには置けません');
    return;
  }
  if (app.world.blocks[key]) return;
  if (boxIntersectsBlock(playerBox(camera.position), nx, ny, nz)) {
    setMessage('自分の位置には置けません');
    return;
  }

  app.world.blocks[key] = app.selected;
  rebuildMeshes();
  setMessage(`${BLOCKS[app.selected].name}を置きました`);
}

function saveWorld() {
  const payload = serializeWorld(app.world, {
    position: { x: camera.position.x, y: camera.position.y, z: camera.position.z },
    selected: app.selected
  });
  localStorage.setItem(SAVE_KEY, payload);
  setMessage('保存しました');
}

function loadWorld() {
  const saved = localStorage.getItem(SAVE_KEY);
  if (!saved) {
    setMessage('保存データがありません');
    return;
  }
  try {
    const data = deserializeWorld(saved);
    app.world = data.world;
    const spawn = data.player?.position || getSpawn(app.world);
    camera.position.set(spawn.x, spawn.y, spawn.z);
    if (data.player?.selected && BLOCKS[data.player.selected]) app.selected = data.player.selected;
    updateHotbar();
    rebuildMeshes();
    setMessage('読み込みました');
  } catch {
    setMessage('読み込みに失敗しました');
  }
}

function resetWorld() {
  app.world = createWorld();
  localStorage.removeItem(SAVE_KEY);
  app.selected = 'grass';
  app.velocityY = 0;
  updateHotbar();
  setSpawn();
  rebuildMeshes();
  setMessage('ワールドをリセットしました');
}

function setMessage(text) {
  message.textContent = text;
  window.clearTimeout(setMessage.timer);
  setMessage.timer = window.setTimeout(() => {
    message.textContent = controls.isLocked ? '探索中' : 'クリックで視点操作';
  }, 2200);
}

function updatePositionLabel() {
  positionLabel.textContent = `x ${camera.position.x.toFixed(1)} / y ${camera.position.y.toFixed(1)} / z ${camera.position.z.toFixed(1)}`;
}

function resizeRenderer() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
}
