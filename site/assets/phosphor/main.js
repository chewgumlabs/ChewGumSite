const W = 320;
const H = 200;
const FOV = Math.PI / 3;
const HALF_FOV = FOV / 2;
const MOVE_SPEED = 3.5;
const TURN_SPEED = 2.2;
const DECAY_ALPHA = 0.22;
const BUCKETS = 20;
const PHCOLOR = '51,255,102';

// 14×14 map — 0 = open, 1 = wall
const MAP_W = 14;
const MAP_H = 14;

// prettier-ignore
const MAP = [
  1,1,1,1,1,1,1,1,1,1,1,1,1,1,
  1,0,0,0,0,0,0,1,0,0,0,0,0,1,
  1,0,1,1,0,1,0,0,0,1,0,1,0,1,
  1,0,1,0,0,1,0,1,0,0,0,0,0,1,
  1,0,0,0,1,0,0,1,0,1,1,1,0,1,
  1,1,1,0,1,0,1,0,0,0,0,1,0,1,
  1,0,0,0,0,0,1,0,1,0,0,0,0,1,
  1,0,1,1,0,0,0,0,1,0,1,0,0,1,
  1,0,0,1,0,1,0,0,0,0,1,0,1,1,
  1,0,0,0,0,1,0,1,0,0,0,0,0,1,
  1,1,0,1,0,0,0,1,0,1,0,1,0,1,
  1,0,0,0,0,1,0,0,0,0,0,0,0,1,
  1,0,0,0,0,0,0,1,0,0,0,0,0,1,
  1,1,1,1,1,1,1,1,1,1,1,1,1,1,
];

const TOTAL_OPEN = MAP.filter((v) => v === 0).length;

function mapAt(x, y) {
  const mx = Math.floor(x);
  const my = Math.floor(y);
  if (mx < 0 || mx >= MAP_W || my < 0 || my >= MAP_H) return 1;
  return MAP[my * MAP_W + mx];
}

function canOccupy(x, y) {
  const m = 0.28;
  return (
    !mapAt(x + m, y + m) &&
    !mapAt(x - m, y + m) &&
    !mapAt(x + m, y - m) &&
    !mapAt(x - m, y - m)
  );
}

const player = { x: 2.5, y: 1.5, angle: 0.0 };

const keys = new Set();
document.addEventListener('keydown', (e) => {
  keys.add(e.code);
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code)) {
    e.preventDefault();
  }
});
document.addEventListener('keyup', (e) => keys.delete(e.code));

const canvas = document.querySelector('#scene');
const ctx = canvas.getContext('2d', { alpha: false });
ctx.imageSmoothingEnabled = false;

const statusEl = document.querySelector('#status');
const armButton = document.querySelector('#audio-trigger');
const stateEl = document.querySelector('#scope-state');
const cellsReadout = document.querySelector('#cells-readout');
const angleReadout = document.querySelector('#angle-readout');
const distReadout = document.querySelector('#dist-readout');
const cellsMeter = document.querySelector('#cells-meter');
const angleMeter = document.querySelector('#angle-meter');
const distMeter = document.querySelector('#dist-meter');

const visited = new Set();

class PhosphorSynth {
  constructor() {
    this.audioCtx = null;
    this.drone = null;
    this.droneGain = null;
    this.masterGain = null;
    this.started = false;
    this.lastChime = -Infinity;
  }

  async arm() {
    if (this.audioCtx) return;
    this.audioCtx = new AudioContext();

    this.masterGain = this.audioCtx.createGain();
    this.masterGain.gain.setValueAtTime(0.6, this.audioCtx.currentTime);
    this.masterGain.connect(this.audioCtx.destination);

    this.drone = this.audioCtx.createOscillator();
    this.drone.type = 'triangle';
    this.drone.frequency.setValueAtTime(55, this.audioCtx.currentTime);

    this.droneGain = this.audioCtx.createGain();
    this.droneGain.gain.setValueAtTime(0.018, this.audioCtx.currentTime);

    this.drone.connect(this.droneGain);
    this.droneGain.connect(this.masterGain);
    this.drone.start();

    this.started = true;
  }

  wallChime(dist) {
    if (!this.started) return;
    const now = this.audioCtx.currentTime;
    if (now - this.lastChime < 0.7) return;
    this.lastChime = now;

    const osc = this.audioCtx.createOscillator();
    const gain = this.audioCtx.createGain();

    osc.type = 'triangle';
    osc.frequency.setValueAtTime(260 + (1 / Math.max(0.1, dist)) * 60, now);
    osc.frequency.exponentialRampToValueAtTime(130, now + 0.35);

    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.16, now + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.38);

    osc.connect(gain);
    gain.connect(this.masterGain);
    osc.start(now);
    osc.stop(now + 0.4);
  }

  setMotion(moving) {
    if (!this.droneGain || !this.audioCtx) return;
    const now = this.audioCtx.currentTime;
    const target = moving ? 0.038 : 0.018;
    this.droneGain.gain.linearRampToValueAtTime(target, now + 0.12);
  }
}

const synth = new PhosphorSynth();

armButton.addEventListener('click', async () => {
  await synth.arm();
  armButton.textContent = 'SIGNAL ARMED';
  armButton.disabled = true;
  stateEl.textContent = 'Navigate with WASD or arrow keys. Corners ring.';
  statusEl.textContent = 'Scanning';
});

// DDA raycaster
function castRay(px, py, angle) {
  const rdx = Math.cos(angle);
  const rdy = Math.sin(angle);

  let mapX = Math.floor(px);
  let mapY = Math.floor(py);

  const ddx = rdx === 0 ? 1e30 : Math.abs(1 / rdx);
  const ddy = rdy === 0 ? 1e30 : Math.abs(1 / rdy);

  const stepX = rdx < 0 ? -1 : 1;
  const stepY = rdy < 0 ? -1 : 1;

  let sdx = rdx < 0 ? (px - mapX) * ddx : (mapX + 1 - px) * ddx;
  let sdy = rdy < 0 ? (py - mapY) * ddy : (mapY + 1 - py) * ddy;

  let side = 0;
  let dist = 20;

  for (let i = 0; i < 64; i++) {
    if (sdx < sdy) {
      sdx += ddx;
      mapX += stepX;
      side = 0;
    } else {
      sdy += ddy;
      mapY += stepY;
      side = 1;
    }
    if (mapAt(mapX, mapY)) {
      dist =
        side === 0
          ? (mapX - px + (1 - stepX) * 0.5) / rdx
          : (mapY - py + (1 - stepY) * 0.5) / rdy;
      break;
    }
  }

  return { dist: Math.max(0.05, dist), side };
}

// Oscilloscope renderer
function render() {
  // Phosphor persistence — dim previous frame rather than clear
  ctx.fillStyle = `rgba(0,0,0,${DECAY_ALPHA})`;
  ctx.fillRect(0, 0, W, H);

  // Cast all columns
  const cols = new Array(W);
  for (let x = 0; x < W; x++) {
    const angle = player.angle - HALF_FOV + (x / W) * FOV;
    const { dist, side } = castRay(player.x, player.y, angle);
    const wallH = Math.min(H, (H / dist) | 0);
    const top = (H - wallH) >> 1;
    cols[x] = { dist, side, top, bottom: top + wallH };
  }

  ctx.save();
  ctx.lineWidth = 1;
  ctx.shadowBlur = 5;
  ctx.shadowColor = `rgb(${PHCOLOR})`;

  // Batch columns by brightness bucket to reduce draw calls
  const buckets = Array.from({ length: BUCKETS }, () => []);
  for (let x = 0; x < W; x++) {
    const { dist, side } = cols[x];
    const b = Math.min(1, 3.2 / (dist * 0.7 + 0.35)) * (side ? 0.52 : 1.0);
    buckets[Math.min(BUCKETS - 1, (b * BUCKETS) | 0)].push(x);
  }
  for (let b = 0; b < BUCKETS; b++) {
    if (!buckets[b].length) continue;
    ctx.strokeStyle = `rgba(${PHCOLOR},${((b + 1) / BUCKETS).toFixed(2)})`;
    ctx.beginPath();
    for (const x of buckets[b]) {
      ctx.moveTo(x + 0.5, cols[x].top);
      ctx.lineTo(x + 0.5, cols[x].bottom);
    }
    ctx.stroke();
  }

  // Bright edge highlights at wall depth transitions
  ctx.shadowBlur = 12;
  ctx.strokeStyle = 'rgba(180,255,200,0.8)';
  ctx.beginPath();
  for (let x = 1; x < W - 1; x++) {
    if (Math.abs(cols[x].top - cols[x - 1].top) > 5) {
      const eTop = Math.min(cols[x].top, cols[x - 1].top);
      const eBot = Math.max(cols[x].bottom, cols[x - 1].bottom);
      ctx.moveTo(x + 0.5, eTop);
      ctx.lineTo(x + 0.5, eBot);
    }
  }
  ctx.stroke();

  ctx.restore();
}

// Update telemetry readouts
function updateTelemetry(fwdDist, moving) {
  visited.add(`${Math.floor(player.x)},${Math.floor(player.y)}`);

  const deg = (((player.angle * 180) / Math.PI) % 360 + 360) % 360;

  cellsReadout.textContent = `${visited.size} / ${TOTAL_OPEN}`;
  angleReadout.textContent = `${deg.toFixed(0)}°`;
  distReadout.textContent = `${fwdDist.toFixed(2)} m`;

  cellsMeter.style.transform = `scaleX(${Math.min(1, visited.size / TOTAL_OPEN).toFixed(3)})`;
  angleMeter.style.transform = `scaleX(${(deg / 360).toFixed(3)})`;
  distMeter.style.transform = `scaleX(${Math.min(1, Math.max(0, 1 - fwdDist / 6)).toFixed(3)})`;

  statusEl.textContent = `${visited.size} cells traced`;

  if (fwdDist < 1.3) synth.wallChime(fwdDist);
  synth.setMotion(moving);
}

// Game loop
let lastTime = 0;

function update(dt) {
  if (keys.has('ArrowLeft') || keys.has('KeyA')) player.angle -= TURN_SPEED * dt;
  if (keys.has('ArrowRight') || keys.has('KeyD')) player.angle += TURN_SPEED * dt;

  let dx = 0;
  let dy = 0;
  if (keys.has('ArrowUp') || keys.has('KeyW')) {
    dx += Math.cos(player.angle);
    dy += Math.sin(player.angle);
  }
  if (keys.has('ArrowDown') || keys.has('KeyS')) {
    dx -= Math.cos(player.angle);
    dy -= Math.sin(player.angle);
  }

  const moving = dx !== 0 || dy !== 0;
  if (moving) {
    const len = Math.hypot(dx, dy);
    const spd = MOVE_SPEED * dt;
    dx = (dx / len) * spd;
    dy = (dy / len) * spd;
    if (canOccupy(player.x + dx, player.y)) player.x += dx;
    if (canOccupy(player.x, player.y + dy)) player.y += dy;
  }

  const fwd = castRay(player.x, player.y, player.angle);
  updateTelemetry(fwd.dist, moving);
}

function loop(ts) {
  const dt = Math.min((ts - lastTime) / 1000, 0.05);
  lastTime = ts;
  update(dt);
  render();
  requestAnimationFrame(loop);
}

requestAnimationFrame((ts) => {
  lastTime = ts;
  loop(ts);
});
