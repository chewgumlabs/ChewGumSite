#[cfg(not(target_arch = "wasm32"))]
fn main() -> Result<(), minifb::Error> {
    software_render::app::App::run()
}

#[cfg(target_arch = "wasm32")]
fn main() {}
