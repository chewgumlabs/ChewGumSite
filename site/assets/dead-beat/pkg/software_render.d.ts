/* tslint:disable */
/* eslint-disable */

export class WasmGame {
    free(): void;
    [Symbol.dispose](): void;
    east_text(): string;
    frame_rgba(): Uint8Array;
    height(): number;
    constructor(width: number, height: number);
    north_text(): string;
    player_angle(): number;
    player_x(): number;
    player_y(): number;
    set_input(forward: boolean, backward: boolean, turn_left: boolean, turn_right: boolean, strafe_left: boolean, strafe_right: boolean): void;
    set_wall_texts(north: string, east: string, south: string, west: string): void;
    south_text(): string;
    update(dt_seconds: number): void;
    west_text(): string;
    width(): number;
}

export function start(): void;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __wbg_wasmgame_free: (a: number, b: number) => void;
    readonly wasmgame_east_text: (a: number) => [number, number];
    readonly wasmgame_frame_rgba: (a: number) => [number, number];
    readonly wasmgame_height: (a: number) => number;
    readonly wasmgame_new: (a: number, b: number) => number;
    readonly wasmgame_north_text: (a: number) => [number, number];
    readonly wasmgame_player_angle: (a: number) => number;
    readonly wasmgame_player_x: (a: number) => number;
    readonly wasmgame_player_y: (a: number) => number;
    readonly wasmgame_set_input: (a: number, b: number, c: number, d: number, e: number, f: number, g: number) => void;
    readonly wasmgame_set_wall_texts: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number, i: number) => void;
    readonly wasmgame_south_text: (a: number) => [number, number];
    readonly wasmgame_update: (a: number, b: number) => void;
    readonly wasmgame_west_text: (a: number) => [number, number];
    readonly wasmgame_width: (a: number) => number;
    readonly start: () => void;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
