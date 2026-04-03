#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$ROOT_DIR/target/wasm32-unknown-unknown/release"
OUTPUT_WASM="$TARGET_DIR/software_render.wasm"
WEB_PKG_DIR="$ROOT_DIR/web/pkg"
SITE_ASSET_DIR="$ROOT_DIR/../../site/assets/dead-beat"

cd "$ROOT_DIR"

cargo build --lib --release --target wasm32-unknown-unknown
wasm-bindgen \
  --target web \
  --out-dir "$WEB_PKG_DIR" \
  "$OUTPUT_WASM"

mkdir -p "$SITE_ASSET_DIR/pkg"
cp "$ROOT_DIR/web/main.js" "$SITE_ASSET_DIR/main.js"
cp "$ROOT_DIR/web/style.css" "$SITE_ASSET_DIR/style.css"
rsync -a --delete "$WEB_PKG_DIR/" "$SITE_ASSET_DIR/pkg/"
