import init, { WasmGame } from "./pkg/software_render.js";

const WIDTH = 320;
const HEIGHT = 200;
const MAX_BPM = 90;
const MOVEMENT_SPEED_CAP = 3.0;
const ROOM_FACE_BOUNDS = {
  north: 1.0,
  east: 11.0,
  south: 11.0,
  west: 1.0,
};
const WALL_INPUT_IDS = ["north-text", "east-text", "south-text", "west-text"];
const WALLS = [
  { id: "north", label: "North", pan: -0.18 },
  { id: "east", label: "East", pan: 0.55 },
  { id: "south", label: "South", pan: 0.12 },
  { id: "west", label: "West", pan: -0.55 },
];
const A_MINOR_TWO_OCTAVES = [57, 59, 60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81];
const NORTH_POOL = A_MINOR_TWO_OCTAVES.filter((midi) => midi >= 64);
const EAST_POOL = A_MINOR_TWO_OCTAVES.filter((midi) => midi <= 69);
const WEST_POOL = A_MINOR_TWO_OCTAVES.filter((midi) => midi >= 60 && midi <= 76);
const SOUTH_CHORDS = [
  { symbol: "I", midi: 48 },
  { symbol: "IV", midi: 53 },
  { symbol: "V", midi: 55 },
  { symbol: "vi", midi: 45 },
  { symbol: "iii", midi: 52 },
];
const CONSONANT_INTERVAL_SCORES = new Map([
  [0, 2],
  [3, 10],
  [4, 11],
  [5, 8],
  [7, 12],
  [8, 10],
  [9, 9],
]);

const keyState = new Set();
const canvas = document.querySelector("#game");
const context = canvas.getContext("2d", { alpha: false });
const status = document.querySelector("#status");
const songQueue = document.querySelector("#song-queue");
const songState = document.querySelector("#song-state");
const audioTrigger = document.querySelector("#audio-trigger");
const wallInputs = WALL_INPUT_IDS.map((id) => document.querySelector(`#${id}`));
const imageData = context.createImageData(WIDTH, HEIGHT);

context.imageSmoothingEnabled = false;

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function lerp(current, target, amount) {
  return current + (target - current) * amount;
}

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

function preventGameScroll(event) {
  if (["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"].includes(event.code)) {
    event.preventDefault();
  }
}

function hashString(value) {
  let hash = 2166136261;

  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }

  return hash >>> 0;
}

function tokenizeText(text) {
  const words = text.toLowerCase().match(/[a-z0-9']+/g);
  return words && words.length ? words : ["silence"];
}

function midiToFrequency(midi) {
  return 440 * Math.pow(2, (midi - 69) / 12);
}

function midiToLabel(midi) {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const octave = Math.floor(midi / 12) - 1;
  return `${names[midi % 12]}${octave}`;
}

function intervalScore(a, b) {
  const distance = Math.abs(a - b);
  const mod = distance % 12;
  let score = CONSONANT_INTERVAL_SCORES.get(mod) ?? -18;

  if (distance < 3) {
    score -= 10;
  }
  if (distance === 0) {
    score -= 4;
  }

  return score;
}

function makeEvent(word, midi, options = {}) {
  const note = midiToLabel(midi);

  return {
    word,
    midi,
    note,
    display: options.display ?? note,
    beats: options.beats ?? 1,
    velocity: options.velocity ?? 0.16,
    seed: options.seed ?? 0,
  };
}

function chooseWestMidi(seed, referenceMidi, previousMidi, previousReferenceMidi) {
  let bestMidi = WEST_POOL[0];
  let bestScore = -Infinity;

  for (const candidate of WEST_POOL) {
    let score = intervalScore(referenceMidi, candidate);
    const referenceMotion = referenceMidi - previousReferenceMidi;
    const candidateMotion = candidate - previousMidi;

    if (candidate <= referenceMidi) {
      score += 3;
    }
    score -= Math.abs(candidate - previousMidi) * 0.28;

    if (
      referenceMotion !== 0 &&
      candidateMotion !== 0 &&
      Math.sign(referenceMotion) !== Math.sign(candidateMotion)
    ) {
      score += 3;
    }

    score += ((seed ^ candidate) & 7) * 0.15;

    if (score > bestScore) {
      bestScore = score;
      bestMidi = candidate;
    }
  }

  return bestMidi;
}

function chooseNorthRepairMidi(referenceMidi, companionMidi, previousMidi) {
  let bestMidi = referenceMidi;
  let bestScore = -Infinity;

  for (const candidate of NORTH_POOL) {
    let score = intervalScore(candidate, companionMidi);

    if (candidate >= companionMidi) {
      score += 2;
    }
    score -= Math.abs(candidate - previousMidi) * 0.22;

    if (score > bestScore) {
      bestScore = score;
      bestMidi = candidate;
    }
  }

  return bestMidi;
}

function buildNorthEvents(words) {
  const startSeed = hashString(`${words.join("|")}:north-start`);
  let poolIndex = 3 + (startSeed % 3);
  const steps = [-2, -1, -1, 1, 1, 2, 2, 3, -3, 4];

  return words.map((word, index) => {
    const seed = hashString(`north:${word}:${index}`);
    poolIndex = clamp(poolIndex + steps[seed % steps.length], 0, NORTH_POOL.length - 1);

    if (index % 4 === 3 && seed % 5 === 0) {
      poolIndex = clamp(poolIndex - 1, 0, NORTH_POOL.length - 1);
    }

    return makeEvent(word, NORTH_POOL[poolIndex], {
      seed,
      velocity: 0.18,
    });
  });
}

function buildEastEvents(words) {
  let poolIndex = hashString(`${words.join("|")}:east-start`) % 3;
  const deltas = [-2, -1, -1, 0, 1, 1, 2];

  return words.map((word, index) => {
    const seed = hashString(`east:${word}:${index}`);
    poolIndex = clamp(poolIndex + deltas[seed % deltas.length], 0, EAST_POOL.length - 1);

    if (poolIndex > 4 && seed % 2 === 0) {
      poolIndex -= 1;
    }
    if (seed % 6 === 0) {
      poolIndex = Math.max(0, poolIndex - 1);
    }

    return makeEvent(word, EAST_POOL[poolIndex], {
      seed,
      velocity: 0.14,
    });
  });
}

function buildSouthEvents(words) {
  const startSeed = hashString(`${words.join("|")}:south-start`);
  let previousChordIndex = startSeed % 2 === 0 ? 0 : 1;

  return words.map((word, index) => {
    let chord = SOUTH_CHORDS[previousChordIndex];
    const seed = hashString(`south:${word}:${index}`);

    if (index > 0) {
      const candidates = SOUTH_CHORDS.filter(
        (_, candidateIndex) => candidateIndex !== previousChordIndex || seed % 4 === 0,
      );
      chord = candidates[seed % candidates.length];
      previousChordIndex = SOUTH_CHORDS.indexOf(chord);
    }

    return makeEvent(word, chord.midi, {
      seed,
      beats: 2,
      velocity: 0.11,
      display: `${chord.symbol} ${midiToLabel(chord.midi)}`,
    });
  });
}

function buildWestEvents(words, northEvents) {
  let previousMidi = WEST_POOL[2];
  let previousNorthMidi = northEvents[0]?.midi ?? NORTH_POOL[2];

  return words.map((word, index) => {
    const seed = hashString(`west:${word}:${index}`);
    const northEvent = northEvents[index % northEvents.length];
    const midi = chooseWestMidi(seed, northEvent.midi, previousMidi, previousNorthMidi);

    previousMidi = midi;
    previousNorthMidi = northEvent.midi;

    return makeEvent(word, midi, {
      seed,
      velocity: 0.16,
    });
  });
}

function balanceNorthWest(northEvents, westEvents) {
  if (!northEvents.length || !westEvents.length) {
    return { north: northEvents, west: westEvents };
  }

  const fixedNorth = northEvents.map((event) => ({ ...event }));
  const fixedWest = westEvents.map((event) => ({ ...event }));
  const maxLength = Math.max(fixedNorth.length, fixedWest.length);
  let previousNorthMidi = fixedNorth[0].midi;
  let previousWestMidi = fixedWest[0].midi;

  for (let index = 0; index < maxLength; index += 1) {
    const northIndex = index % fixedNorth.length;
    const westIndex = index % fixedWest.length;
    const north = fixedNorth[northIndex];
    const west = fixedWest[westIndex];

    if (intervalScore(north.midi, west.midi) < 4) {
      const repairedWestMidi = chooseWestMidi(
        hashString(`repair-west:${west.word}:${index}:${north.midi}`),
        north.midi,
        previousWestMidi,
        previousNorthMidi,
      );

      fixedWest[westIndex] = makeEvent(west.word, repairedWestMidi, {
        seed: west.seed,
        beats: west.beats,
        velocity: west.velocity,
      });
    }

    if (Math.abs(fixedNorth[northIndex].midi - fixedWest[westIndex].midi) < 3) {
      const repairedNorthMidi = chooseNorthRepairMidi(
        fixedNorth[northIndex].midi,
        fixedWest[westIndex].midi,
        previousNorthMidi,
      );

      fixedNorth[northIndex] = makeEvent(fixedNorth[northIndex].word, repairedNorthMidi, {
        seed: fixedNorth[northIndex].seed,
        beats: fixedNorth[northIndex].beats,
        velocity: fixedNorth[northIndex].velocity,
      });
    }

    previousNorthMidi = fixedNorth[northIndex].midi;
    previousWestMidi = fixedWest[westIndex].midi;
  }

  return {
    north: fixedNorth,
    west: fixedWest,
  };
}

function buildComposition(wallTexts) {
  const northWords = tokenizeText(wallTexts.north);
  const eastWords = tokenizeText(wallTexts.east);
  const southWords = tokenizeText(wallTexts.south);
  const westWords = tokenizeText(wallTexts.west);

  const northEvents = buildNorthEvents(northWords);
  const eastEvents = buildEastEvents(eastWords);
  const southEvents = buildSouthEvents(southWords);
  const westEvents = buildWestEvents(westWords, northEvents);
  const pair = balanceNorthWest(northEvents, westEvents);

  return {
    north: { label: "North", events: pair.north },
    east: { label: "East", events: eastEvents },
    south: { label: "South", events: southEvents },
    west: { label: "West", events: pair.west },
  };
}

function buildQueueMarkup(composition, voiceStates) {
  return WALLS.map((wall) => {
    const events = composition[wall.id]?.events ?? [];
    const activeIndex = voiceStates?.[wall.id]?.activeIndex ?? -1;
    const notesMarkup = events
      .slice(0, 12)
      .map((event, index) => {
        const currentClass = index === activeIndex ? " is-current" : "";
        return `<span class="queue-note${currentClass}" title="${event.word}">${event.display}</span>`;
      })
      .join("");

    return `
      <div class="queue-row">
        <span class="queue-wall">${wall.label}</span>
        <div class="queue-notes">${notesMarkup || '<span class="queue-note">...</span>'}</div>
      </div>
    `;
  }).join("");
}

function createNesTriangleWave(audioContext) {
  const stepValues = [
    15, 14, 13, 12, 11, 10, 9, 8,
    7, 6, 5, 4, 3, 2, 1, 0,
    0, 1, 2, 3, 4, 5, 6, 7,
    8, 9, 10, 11, 12, 13, 14, 15,
  ];
  const normalized = stepValues.map((value) => (value / 15) * 2 - 1);
  const mean =
    normalized.reduce((sum, value) => sum + value, 0) / normalized.length;
  const samples = normalized.map((value) => value - mean);
  const harmonicCount = 24;
  const real = new Float32Array(harmonicCount + 1);
  const imag = new Float32Array(harmonicCount + 1);

  for (let harmonic = 1; harmonic <= harmonicCount; harmonic += 1) {
    let cosineSum = 0;
    let sineSum = 0;

    for (let sampleIndex = 0; sampleIndex < samples.length; sampleIndex += 1) {
      const phase = (2 * Math.PI * harmonic * sampleIndex) / samples.length;
      cosineSum += samples[sampleIndex] * Math.cos(phase);
      sineSum += samples[sampleIndex] * Math.sin(phase);
    }

    real[harmonic] = (2 / samples.length) * cosineSum;
    imag[harmonic] = (2 / samples.length) * sineSum;
  }

  return audioContext.createPeriodicWave(real, imag, {
    disableNormalization: true,
  });
}

class MusicVoice {
  constructor(audioContext, periodicWave, destination, pan) {
    this.audioContext = audioContext;
    this.oscillator = new OscillatorNode(audioContext);
    this.filter = new BiquadFilterNode(audioContext, {
      type: "lowpass",
      frequency: 1300,
      Q: 0.2,
    });
    this.noteGain = new GainNode(audioContext, { gain: 0.0001 });
    this.rangeGain = new GainNode(audioContext, { gain: 0.0001 });
    this.panNode =
      typeof StereoPannerNode === "function"
        ? new StereoPannerNode(audioContext, { pan })
        : new GainNode(audioContext);

    this.oscillator.setPeriodicWave(periodicWave);
    this.oscillator.connect(this.filter);
    this.filter.connect(this.noteGain);
    this.noteGain.connect(this.rangeGain);
    this.rangeGain.connect(this.panNode);
    this.panNode.connect(destination);
    this.oscillator.start();
  }

  setRangeGain(value, time) {
    const safeValue = Math.max(0.0001, value);
    this.rangeGain.gain.cancelScheduledValues(time);
    this.rangeGain.gain.linearRampToValueAtTime(safeValue, time + 0.12);
  }

  play(event, time, beatDuration) {
    const duration = Math.max(0.08, beatDuration * event.beats * 0.88);
    const peak = event.velocity;

    this.oscillator.frequency.cancelScheduledValues(time);
    this.oscillator.frequency.setValueAtTime(midiToFrequency(event.midi), time);

    this.noteGain.gain.cancelScheduledValues(time);
    this.noteGain.gain.setValueAtTime(0.0001, time);
    this.noteGain.gain.linearRampToValueAtTime(peak, time + 0.02);
    this.noteGain.gain.exponentialRampToValueAtTime(
      Math.max(0.0001, peak * 0.45),
      time + duration * 0.6,
    );
    this.noteGain.gain.exponentialRampToValueAtTime(0.0001, time + duration);
  }

  silence(time) {
    this.noteGain.gain.cancelScheduledValues(time);
    this.noteGain.gain.setTargetAtTime(0.0001, time, 0.03);
    this.rangeGain.gain.cancelScheduledValues(time);
    this.rangeGain.gain.setTargetAtTime(0.0001, time, 0.03);
  }
}

class MusicBox {
  constructor(queueElement, stateElement, statusElement) {
    this.queueElement = queueElement;
    this.stateElement = stateElement;
    this.statusElement = statusElement;
    this.audioContext = null;
    this.masterGain = null;
    this.voices = null;
    this.started = false;
    this.currentBpm = 0;
    this.movementEnergy = 0;
    this.beatAccumulator = 0;
    this.composition = buildComposition({
      north: "",
      east: "",
      south: "",
      west: "",
    });
    this.voiceStates = this.createVoiceStates();
  }

  createVoiceStates() {
    return Object.fromEntries(
      WALLS.map((wall) => [
        wall.id,
        {
          index: 0,
          holdSteps: 0,
          activeIndex: -1,
        },
      ]),
    );
  }

  setWallTexts(wallTexts) {
    this.composition = buildComposition(wallTexts);
    this.voiceStates = this.createVoiceStates();
    this.beatAccumulator = 0;

    if (this.audioContext && this.voices) {
      const now = this.audioContext.currentTime;
      for (const voice of Object.values(this.voices)) {
        voice.silence(now);
      }
    }

    this.renderQueue();
    this.updateStateText();
  }

  async arm() {
    if (!this.audioContext) {
      this.setupAudio();
    }

    await this.audioContext.resume();
    this.started = true;
    this.currentBpm = 0;
    this.movementEnergy = 0;
    this.beatAccumulator = 0;
    this.voiceStates = this.createVoiceStates();

    const now = this.audioContext.currentTime;
    for (const voice of Object.values(this.voices)) {
      voice.silence(now);
    }

    this.statusElement.textContent = "Song armed";
    this.renderQueue();
    this.updateStateText();
  }

  setupAudio() {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;

    if (!AudioContextCtor) {
      throw new Error("Web Audio is unavailable in this browser.");
    }

    this.audioContext = new AudioContextCtor();
    this.masterGain = new GainNode(this.audioContext, { gain: 0.12 });
    this.masterGain.connect(this.audioContext.destination);

    const periodicWave = createNesTriangleWave(this.audioContext);
    this.voices = Object.fromEntries(
      WALLS.map((wall) => [
        wall.id,
        new MusicVoice(this.audioContext, periodicWave, this.masterGain, wall.pan),
      ]),
    );
  }

  update(dtSeconds, playerX, playerY, movementSpeed) {
    const movementRatio = clamp(movementSpeed / MOVEMENT_SPEED_CAP, 0, 1);
    const energyRate = movementRatio > this.movementEnergy ? 3.2 : 0.65;
    const energyBlend = 1 - Math.exp(-dtSeconds * energyRate);

    this.movementEnergy = lerp(this.movementEnergy, movementRatio, energyBlend);

    const targetBpm = this.started ? this.movementEnergy * MAX_BPM : 0;
    const bpmBlend = 1 - Math.exp(-dtSeconds * 2.4);
    this.currentBpm = lerp(this.currentBpm, targetBpm, bpmBlend);

    if (this.audioContext && this.voices) {
      this.updateSpatialMix(playerX, playerY, this.audioContext.currentTime);
    }

    this.updateStateText();

    if (!this.started || !this.audioContext || this.currentBpm < 1) {
      return;
    }

    this.beatAccumulator += (this.currentBpm / 60) * dtSeconds;

    while (this.beatAccumulator >= 1) {
      this.beatAccumulator -= 1;
      this.advanceBeat();
    }
  }

  updateSpatialMix(playerX, playerY, time) {
    if (!this.started) {
      for (const voice of Object.values(this.voices)) {
        voice.setRangeGain(0.0001, time);
      }
      return;
    }

    const distances = {
      north: Math.max(0, playerY - ROOM_FACE_BOUNDS.north),
      east: Math.max(0, ROOM_FACE_BOUNDS.east - playerX),
      south: Math.max(0, ROOM_FACE_BOUNDS.south - playerY),
      west: Math.max(0, playerX - ROOM_FACE_BOUNDS.west),
    };

    for (const wall of WALLS) {
      const normalizedDistance = 1 - clamp(distances[wall.id] / 10, 0, 1);
      const gain = 0.03 + normalizedDistance * 0.12;
      this.voices[wall.id].setRangeGain(gain, time);
    }
  }

  advanceBeat() {
    const beatDuration = 60 / Math.max(this.currentBpm, 18);
    const time = this.audioContext.currentTime + 0.03;

    for (const wall of WALLS) {
      this.advanceVoice(wall.id, time, beatDuration);
    }

    this.renderQueue();
  }

  advanceVoice(wallId, time, beatDuration) {
    const state = this.voiceStates[wallId];
    const events = this.composition[wallId]?.events ?? [];

    if (!events.length) {
      return;
    }

    if (state.holdSteps > 0) {
      state.holdSteps -= 1;
      return;
    }

    const eventIndex = state.index % events.length;
    const event = events[eventIndex];

    this.voices[wallId].play(event, time, beatDuration);
    state.activeIndex = eventIndex;
    state.index += 1;
    state.holdSteps = Math.max(0, event.beats - 1);
  }

  updateStateText() {
    if (!this.stateElement) {
      return;
    }

    if (!this.started) {
      this.stateElement.textContent =
        "Press MOVE THROUGH YOUR SONG. Walking winds the room until it aches at 90 BPM.";
      return;
    }

    if (this.currentBpm < 4) {
      this.stateElement.textContent =
        "The room is barely turning. Walk to wind the song back into motion.";
      return;
    }

    this.stateElement.textContent =
      `Walking winds the room to ${Math.round(this.currentBpm)} BPM. ` +
      "When you stop, it slowly falls back asleep.";
  }

  renderQueue() {
    if (!this.queueElement) {
      return;
    }

    this.queueElement.innerHTML = buildQueueMarkup(this.composition, this.voiceStates);
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

function readWallTexts() {
  return {
    north: wallInputs[0].value,
    east: wallInputs[1].value,
    south: wallInputs[2].value,
    west: wallInputs[3].value,
  };
}

async function boot() {
  status.textContent = "Loading module";
  await init();

  const game = new WasmGame(WIDTH, HEIGHT);
  const musicBox = new MusicBox(songQueue, songState, status);
  let lastTime = performance.now();
  let inputTimer = null;
  let previousPlayer = {
    x: game.player_x(),
    y: game.player_y(),
  };

  wallInputs[0].value = game.north_text();
  wallInputs[1].value = game.east_text();
  wallInputs[2].value = game.south_text();
  wallInputs[3].value = game.west_text();

  musicBox.setWallTexts(readWallTexts());
  status.textContent = "Room waiting";

  for (const input of wallInputs) {
    input.addEventListener("focus", () => {
      keyState.clear();
    });
  }

  function applyWallText() {
    const wallTexts = readWallTexts();
    game.set_wall_texts(
      wallTexts.north,
      wallTexts.east,
      wallTexts.south,
      wallTexts.west,
    );
    previousPlayer = {
      x: game.player_x(),
      y: game.player_y(),
    };
    musicBox.setWallTexts(wallTexts);
    status.textContent = "Walls listening";
  }

  for (const input of wallInputs) {
    input.addEventListener("input", () => {
      status.textContent = "Updating walls";
      window.clearTimeout(inputTimer);
      inputTimer = window.setTimeout(applyWallText, 120);
    });
  }

  if (audioTrigger) {
    audioTrigger.addEventListener("click", async () => {
      try {
        await musicBox.arm();
      } catch (error) {
        status.textContent = "Audio failed";
        if (songState) {
          songState.textContent = error instanceof Error ? error.message : String(error);
        }
        console.error(error);
      }
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

    const currentPlayer = {
      x: game.player_x(),
      y: game.player_y(),
    };
    const movementSpeed =
      Math.hypot(currentPlayer.x - previousPlayer.x, currentPlayer.y - previousPlayer.y) /
      Math.max(dtSeconds, 0.0001);

    musicBox.update(dtSeconds, currentPlayer.x, currentPlayer.y, movementSpeed);
    previousPlayer = currentPlayer;

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
}

boot().catch((error) => {
  status.textContent = "Boot failed";
  if (songState) {
    songState.textContent = error instanceof Error ? error.message : String(error);
  }
  console.error(error);
});
