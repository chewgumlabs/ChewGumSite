import init, { WasmGame } from "./pkg/software_render.js";

const WIDTH = 320;
const HEIGHT = 200;
const keyState = new Set();
const WALL_INPUT_IDS = ["north-text", "east-text", "south-text", "west-text"];

const canvas = document.querySelector("#game");
const context = canvas.getContext("2d", { alpha: false });
const status = document.querySelector("#status");
const telemetry = document.querySelector("#telemetry");
const wallInputs = WALL_INPUT_IDS.map((id) => document.querySelector(`#${id}`));

context.imageSmoothingEnabled = false;

const imageData = context.createImageData(WIDTH, HEIGHT);

function isPressed(code) {
  return keyState.has(code);
}

function isEditableTarget(target) {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "TEXTAREA" ||
      target.tagName === "INPUT" ||
      target.isContentEditable)
  );
}

function refreshTelemetry(game) {
  telemetry.textContent =
    `x ${game.player_x().toFixed(2)}  y ${game.player_y().toFixed(2)}  a ${game.player_angle().toFixed(2)}`;
}

function preventGameScroll(event) {
  if (["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"].includes(event.code)) {
    event.preventDefault();
  }
}

window.addEventListener("keydown", (event) => {
  if (isEditableTarget(event.target)) {
    return;
  }

  preventGameScroll(event);
  keyState.add(event.code);
});

window.addEventListener("keyup", (event) => {
  if (isEditableTarget(event.target)) {
    return;
  }

  preventGameScroll(event);
  keyState.delete(event.code);
});

window.addEventListener("blur", () => {
  keyState.clear();
});

async function boot() {
  status.textContent = "Loading module";
  await init();

  const game = new WasmGame(WIDTH, HEIGHT);
  let lastTime = performance.now();
  let inputTimer = null;

  wallInputs[0].value = game.north_text();
  wallInputs[1].value = game.east_text();
  wallInputs[2].value = game.south_text();
  wallInputs[3].value = game.west_text();

  for (const input of wallInputs) {
    input.addEventListener("focus", () => {
      keyState.clear();
    });
  }

  status.textContent = "Running";
  refreshTelemetry(game);

  function applyWallText() {
    game.set_wall_texts(
      wallInputs[0].value,
      wallInputs[1].value,
      wallInputs[2].value,
      wallInputs[3].value,
    );
    status.textContent = "Running";
  }

  for (const input of wallInputs) {
    input.addEventListener("input", () => {
      status.textContent = "Updating walls";
      window.clearTimeout(inputTimer);

      inputTimer = window.setTimeout(applyWallText, 120);
    });
  }

  function frame(now) {
    const dtSeconds = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;

    game.set_input(
      isPressed("KeyW"),
      isPressed("KeyS"),
      isPressed("KeyA"),
      isPressed("KeyD"),
      isPressed("KeyQ"),
      isPressed("KeyE"),
    );
    game.update(dtSeconds);

    imageData.data.set(game.frame_rgba());
    context.putImageData(imageData, 0, 0);
    refreshTelemetry(game);

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

boot().catch((error) => {
  status.textContent = "Boot failed";
  telemetry.textContent = error instanceof Error ? error.message : String(error);
  console.error(error);
});
