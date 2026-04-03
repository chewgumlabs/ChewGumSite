use std::f32::consts::TAU;

pub struct Player {
    pub x: f32,
    pub y: f32,
    pub angle: f32,
    pub move_speed: f32,
    pub turn_speed: f32,
}

impl Player {
    pub fn spawn() -> Self {
        Self::spawn_at(3.5, 3.5)
    }

    pub fn spawn_at(x: f32, y: f32) -> Self {
        Self {
            x,
            y,
            angle: 0.0,
            move_speed: 3.0,
            turn_speed: 2.4,
        }
    }

    pub fn rotate(&mut self, delta: f32) {
        self.angle = (self.angle + delta).rem_euclid(TAU);
    }
}
