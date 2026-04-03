use crate::framebuffer::Framebuffer;
use crate::input::InputState;
use crate::player::Player;
use crate::renderer::Renderer;
use crate::world::{WallFace, World};

pub struct Game {
    framebuffer: Framebuffer,
    player: Player,
    renderer: Renderer,
    world: World,
}

impl Game {
    pub fn new(width: usize, height: usize) -> Self {
        let world = World::demo();
        let (spawn_x, spawn_y) = world.spawn_point();

        Self {
            framebuffer: Framebuffer::new(width, height),
            player: Player::spawn_at(spawn_x, spawn_y),
            renderer: Renderer::new(),
            world,
        }
    }

    pub fn set_wall_texts(&mut self, north: &str, east: &str, south: &str, west: &str) {
        self.world = World::from_wall_inputs([
            north.to_string(),
            east.to_string(),
            south.to_string(),
            west.to_string(),
        ]);
        let (spawn_x, spawn_y) = self.world.spawn_point();
        self.player = Player::spawn_at(spawn_x, spawn_y);
        self.render();
    }

    pub fn render(&mut self) {
        self.renderer
            .render(&mut self.framebuffer, &self.world, &self.player);
    }

    pub fn step(&mut self, input: &InputState, dt: f32) {
        self.update(input, dt);
        self.render();
    }

    pub fn framebuffer(&self) -> &Framebuffer {
        &self.framebuffer
    }

    pub fn framebuffer_rgba(&self) -> Vec<u8> {
        self.framebuffer.to_rgba_bytes()
    }

    pub fn width(&self) -> usize {
        self.framebuffer.width
    }

    pub fn height(&self) -> usize {
        self.framebuffer.height
    }

    pub fn player_x(&self) -> f32 {
        self.player.x
    }

    pub fn player_y(&self) -> f32 {
        self.player.y
    }

    pub fn player_angle(&self) -> f32 {
        self.player.angle
    }

    pub fn wall_text(&self, face: WallFace) -> &str {
        self.world.wall_input(face)
    }

    fn update(&mut self, input: &InputState, dt: f32) {
        let mut rotation_dir = 0.0;
        if input.turn_left {
            rotation_dir -= 1.0;
        }
        if input.turn_right {
            rotation_dir += 1.0;
        }

        let turn_speed = self.player.turn_speed;
        self.player.rotate(rotation_dir * turn_speed * dt);

        let mut move_dir = 0.0;
        if input.forward {
            move_dir += 1.0;
        }
        if input.backward {
            move_dir -= 1.0;
        }

        let step = self.player.move_speed * dt;
        let forward_x = self.player.angle.cos();
        let forward_y = self.player.angle.sin();

        let dx = forward_x * move_dir * step;
        let dy = forward_y * move_dir * step;

        self.try_move(dx, dy);
    }

    fn try_move(&mut self, dx: f32, dy: f32) {
        let next_x = self.player.x + dx;
        if !self.world.is_wall_at(next_x, self.player.y) {
            self.player.x = next_x;
        }

        let next_y = self.player.y + dy;
        if !self.world.is_wall_at(self.player.x, next_y) {
            self.player.y = next_y;
        }
    }
}
