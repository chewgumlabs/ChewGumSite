#[cfg(not(target_arch = "wasm32"))]
pub mod app;
pub mod framebuffer;
pub mod game;
pub mod input;
pub mod player;
pub mod renderer;
#[cfg(target_arch = "wasm32")]
pub mod wasm_app;
pub mod world;

#[cfg(target_arch = "wasm32")]
pub use wasm_app::WasmGame;
