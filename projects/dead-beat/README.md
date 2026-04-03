# Dead Beat

A small Rust scaffold for a software-rendered retro 3D project, now folded into
the `shanecurry.com` site repo as a playable blog page.

This is still a tiny grid raycaster, not a full DOOM-style sector engine, but
it now has two front ends:

- a native desktop window
- a browser page powered by Rust and WebAssembly

## What is included

- A shared Rust game core
- A CPU framebuffer
- A tiny first-person renderer
- A demo map
- Native desktop controls
- A retro-styled web page shell

## Desktop controls

- `W` / `S`: move forward and backward
- `A` / `D`: turn left and right
- `Q` / `E`: strafe left and right
- `Esc`: quit

## Native run

```bash
cargo run
```

## Web build

Install the WebAssembly target once:

```bash
rustup target add wasm32-unknown-unknown
```

Install the binding generator once:

```bash
cargo install wasm-bindgen-cli
```

Then build the web version:

```bash
./scripts/build-web.sh
```

That command now does two things:

- rebuilds the standalone `web/` demo
- publishes the current browser assets into `../../site/assets/dead-beat/`

For a local standalone preview, serve the `web` folder with any static server:

```bash
python3 -m http.server 8000 --directory web
```

Then open:

```text
http://localhost:8000
```

## File layout

- `src/game.rs`: shared update/render orchestration
- `src/app.rs`: native window loop
- `src/wasm_app.rs`: WebAssembly exports
- `src/framebuffer.rs`: software pixel buffer helpers
- `src/renderer.rs`: the 3D view and minimap
- `src/world.rs`: the demo map
- `web/index.html`: browser shell
- `web/main.js`: browser runtime loop and input
- `web/style.css`: fake-game presentation
- `../../site/blog/dead-beat/index.html`: published blog page
- `../../site/assets/dead-beat/`: published static assets for GitHub Pages

## Good next steps

1. Add mouse-look and pointer lock in the browser.
2. Replace the grid map with sectors.
3. Add sprites, doors, and better collision.
4. Split the renderer into wall, floor, and sprite passes.
5. Make wall text importable from post content or query params.
