use wasm_bindgen::prelude::*;

use crate::game::Game;
use crate::input::InputState;
use crate::world::WallFace;

#[wasm_bindgen]
pub struct WasmGame {
    game: Game,
    input: InputState,
}

#[wasm_bindgen]
impl WasmGame {
    #[wasm_bindgen(constructor)]
    pub fn new(width: u32, height: u32) -> Self {
        let mut game = Game::new(width as usize, height as usize);
        game.render();

        Self {
            game,
            input: InputState::default(),
        }
    }

    pub fn set_input(
        &mut self,
        forward: bool,
        backward: bool,
        turn_left: bool,
        turn_right: bool,
        strafe_left: bool,
        strafe_right: bool,
    ) {
        self.input = InputState {
            forward,
            backward,
            turn_left,
            turn_right,
            strafe_left,
            strafe_right,
        };
    }

    pub fn update(&mut self, dt_seconds: f32) {
        self.game.step(&self.input, dt_seconds);
    }

    pub fn set_wall_texts(&mut self, north: String, east: String, south: String, west: String) {
        self.game.set_wall_texts(&north, &east, &south, &west);
    }

    pub fn north_text(&self) -> String {
        self.game.wall_text(WallFace::North).to_string()
    }

    pub fn east_text(&self) -> String {
        self.game.wall_text(WallFace::East).to_string()
    }

    pub fn south_text(&self) -> String {
        self.game.wall_text(WallFace::South).to_string()
    }

    pub fn west_text(&self) -> String {
        self.game.wall_text(WallFace::West).to_string()
    }

    pub fn width(&self) -> u32 {
        self.game.width() as u32
    }

    pub fn height(&self) -> u32 {
        self.game.height() as u32
    }

    pub fn player_x(&self) -> f32 {
        self.game.player_x()
    }

    pub fn player_y(&self) -> f32 {
        self.game.player_y()
    }

    pub fn player_angle(&self) -> f32 {
        self.game.player_angle()
    }

    pub fn frame_rgba(&self) -> Vec<u8> {
        self.game.framebuffer_rgba()
    }
}

#[wasm_bindgen(start)]
pub fn start() {
    console_error_panic_hook::set_once();
}
