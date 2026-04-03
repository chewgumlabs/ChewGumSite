use std::time::Instant;

use minifb::{Key, Scale, Window, WindowOptions};

use crate::game::Game;
use crate::input::InputState;

const SCREEN_WIDTH: usize = 320;
const SCREEN_HEIGHT: usize = 200;

pub struct App {
    game: Game,
    previous_frame: Instant,
    window: Window,
}

impl App {
    pub fn run() -> Result<(), minifb::Error> {
        let mut app = Self::new()?;
        app.game_loop()
    }

    fn new() -> Result<Self, minifb::Error> {
        let mut window = Window::new(
            "Rust Software Renderer",
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            WindowOptions {
                resize: false,
                scale: Scale::X2,
                ..WindowOptions::default()
            },
        )?;

        window.set_target_fps(60);

        Ok(Self {
            game: Game::new(SCREEN_WIDTH, SCREEN_HEIGHT),
            previous_frame: Instant::now(),
            window,
        })
    }

    fn game_loop(&mut self) -> Result<(), minifb::Error> {
        self.game.render();

        while self.window.is_open() && !self.window.is_key_down(Key::Escape) {
            let now = Instant::now();
            let dt = (now - self.previous_frame).as_secs_f32().min(0.05);
            self.previous_frame = now;

            let input = InputState {
                forward: self.window.is_key_down(Key::W),
                backward: self.window.is_key_down(Key::S),
                turn_left: self.window.is_key_down(Key::A),
                turn_right: self.window.is_key_down(Key::D),
                strafe_left: self.window.is_key_down(Key::Q),
                strafe_right: self.window.is_key_down(Key::E),
            };

            self.game.step(&input, dt);

            self.window.update_with_buffer(
                self.game.framebuffer().pixels(),
                SCREEN_WIDTH,
                SCREEN_HEIGHT,
            )?;
        }

        Ok(())
    }
}
