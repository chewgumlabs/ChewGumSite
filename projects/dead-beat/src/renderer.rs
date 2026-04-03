use std::f32::consts::FRAC_PI_3;

use font8x8::{UnicodeFonts, BASIC_FONTS};

use crate::framebuffer::Framebuffer;
use crate::player::Player;
use crate::world::{WallFace, World};

const SKY_COLOR: u32 = 0x365F3B;
const FLOOR_COLOR: u32 = 0x08140A;
const WALL_TEXTURE_SIZE: usize = 64;
const TEXT_ROWS_PER_WALL: usize = 4;
const TEXT_ROW_HEIGHT: usize = WALL_TEXTURE_SIZE / TEXT_ROWS_PER_WALL;
const FONT_SCALE: usize = 2;
const FONT_SIZE: usize = 8;
const CHAR_ADVANCE: usize = FONT_SIZE * FONT_SCALE;
const WALL_BASE_COLOR: u32 = 0x124917;
const WALL_TEXT_COLOR: u32 = 0xB8FFBE;
pub struct Renderer {
    fov: f32,
    max_depth: f32,
    ray_step: f32,
    wall_scale: f32,
}

impl Renderer {
    pub fn new() -> Self {
        Self {
            fov: FRAC_PI_3,
            max_depth: 20.0,
            ray_step: 0.02,
            wall_scale: 0.9,
        }
    }

    pub fn render(&self, framebuffer: &mut Framebuffer, world: &World, player: &Player) {
        framebuffer.clear(0x000000);

        let horizon = framebuffer.height / 2;
        framebuffer.fill_rect(0, 0, framebuffer.width, horizon, SKY_COLOR);
        framebuffer.fill_rect(
            0,
            horizon,
            framebuffer.width,
            framebuffer.height - horizon,
            FLOOR_COLOR,
        );

        for screen_x in 0..framebuffer.width {
            let ray_percent = screen_x as f32 / framebuffer.width as f32;
            let ray_angle = player.angle - self.fov * 0.5 + self.fov * ray_percent;
            let ray_dir_x = ray_angle.cos();
            let ray_dir_y = ray_angle.sin();

            let mut distance = 0.0;
            let mut hit_x = 0.0;
            let mut hit_y = 0.0;
            let mut hit_tile_x = 0usize;
            let mut hit_tile_y = 0usize;
            let mut hit_vertical = false;
            let mut hit_wall = false;

            while distance < self.max_depth {
                distance += self.ray_step;

                let sample_x = player.x + ray_dir_x * distance;
                let sample_y = player.y + ray_dir_y * distance;

                if world.is_wall_at(sample_x, sample_y) {
                    let tile_x = sample_x - sample_x.floor();
                    let tile_y = sample_y - sample_y.floor();
                    let edge_dist_x = tile_x.min(1.0 - tile_x);
                    let edge_dist_y = tile_y.min(1.0 - tile_y);

                    hit_x = sample_x;
                    hit_y = sample_y;
                    hit_tile_x = sample_x.floor() as usize;
                    hit_tile_y = sample_y.floor() as usize;
                    hit_vertical = edge_dist_x < edge_dist_y;
                    hit_wall = true;
                    break;
                }
            }

            if !hit_wall {
                continue;
            }

            let corrected_distance =
                (distance * (ray_angle - player.angle).cos()).max(self.ray_step);
            let wall_height = ((framebuffer.height as f32 / corrected_distance) * self.wall_scale)
                .min(framebuffer.height as f32);

            let wall_top = ((framebuffer.height as f32 - wall_height) * 0.5).round() as i32;
            let wall_bottom = (wall_top as f32 + wall_height).round() as i32;
            let wall_face = world.wall_face_for_hit(hit_tile_x, hit_tile_y, hit_vertical);
            let wall_u = wall_face.and_then(|face| world.wall_u(face, hit_x, hit_y));

            self.draw_wall_column(
                framebuffer,
                world,
                screen_x,
                wall_top,
                wall_bottom,
                wall_face,
                wall_u,
                distance,
                hit_vertical,
            );
        }
    }

    fn draw_wall_column(
        &self,
        framebuffer: &mut Framebuffer,
        world: &World,
        screen_x: usize,
        wall_top: i32,
        wall_bottom: i32,
        wall_face: Option<WallFace>,
        wall_u: Option<f32>,
        distance: f32,
        hit_vertical: bool,
    ) {
        let start = wall_top.clamp(0, framebuffer.height as i32);
        let end = wall_bottom.clamp(0, framebuffer.height as i32);
        let span = (wall_bottom - wall_top).max(1) as f32;
        let side_shade = if hit_vertical { 0.82 } else { 1.0 };

        for screen_y in start..end {
            let texture_v = ((screen_y - wall_top) as f32 / span).clamp(0.0, 0.999);
            let texture_y = (texture_v * WALL_TEXTURE_SIZE as f32) as usize;
            let color = self.wall_texel(world, wall_face, wall_u, texture_y, distance, side_shade);
            framebuffer.set_pixel(screen_x, screen_y as usize, color);
        }
    }

    fn wall_texel(
        &self,
        world: &World,
        wall_face: Option<WallFace>,
        wall_u: Option<f32>,
        texture_y: usize,
        distance: f32,
        side_shade: f32,
    ) -> u32 {
        let text_alpha = wall_face
            .zip(wall_u)
            .map(|(face, u)| self.wall_text_alpha(world, face, u, texture_y))
            .unwrap_or(0.0);
        let texel_color = self.blend_color(WALL_BASE_COLOR, WALL_TEXT_COLOR, text_alpha);

        self.shade_wall(texel_color, distance, side_shade)
    }

    fn wall_text_alpha(&self, world: &World, face: WallFace, wall_u: f32, texture_y: usize) -> f32 {
        let line_index = texture_y / TEXT_ROW_HEIGHT;
        let lines = world.wall_lines(face);

        if line_index >= lines.len() {
            return 0.0;
        }

        let text = &lines[line_index];
        if text.is_empty() {
            return 0.0;
        }

        let glyph_y = (texture_y % TEXT_ROW_HEIGHT) / FONT_SCALE;
        if glyph_y >= FONT_SIZE {
            return 0.0;
        }

        let wall_pixel_width = world.wall_span_tiles(face) * WALL_TEXTURE_SIZE;
        let text_pixel_width = text.chars().count() * CHAR_ADVANCE;
        let start_x = wall_pixel_width.saturating_sub(text_pixel_width) / 2;
        let wall_x = (wall_u.clamp(0.0, 0.999) * wall_pixel_width as f32).floor() as usize;

        if wall_x < start_x || wall_x >= start_x + text_pixel_width {
            return 0.0;
        }

        let char_index = (wall_x - start_x) / CHAR_ADVANCE;
        let glyph_x = ((wall_x - start_x) % CHAR_ADVANCE) / FONT_SCALE;
        let ch = text.chars().nth(char_index).unwrap_or(' ');
        let glyph = BASIC_FONTS
            .get(ch)
            .or_else(|| BASIC_FONTS.get(ch.to_ascii_uppercase()))
            .unwrap_or([0; FONT_SIZE]);

        if (glyph[glyph_y] & (1 << glyph_x)) != 0 {
            0.9
        } else {
            0.0
        }
    }

    fn blend_color(&self, base: u32, overlay: u32, alpha: f32) -> u32 {
        if alpha <= 0.0 {
            return base;
        }

        let inv_alpha = 1.0 - alpha;
        let red = (((base >> 16) & 0xFF) as f32 * inv_alpha
            + ((overlay >> 16) & 0xFF) as f32 * alpha) as u32;
        let green = (((base >> 8) & 0xFF) as f32 * inv_alpha
            + ((overlay >> 8) & 0xFF) as f32 * alpha) as u32;
        let blue = ((base & 0xFF) as f32 * inv_alpha + (overlay & 0xFF) as f32 * alpha) as u32;

        (red << 16) | (green << 8) | blue
    }

    fn shade_wall(&self, color: u32, distance: f32, side_shade: f32) -> u32 {
        let distance_shade = (1.0 / (1.0 + distance * distance * 0.12)).clamp(0.18, 1.0);
        let shade = distance_shade * side_shade;

        let red = (((color >> 16) & 0xFF) as f32 * shade) as u32;
        let green = (((color >> 8) & 0xFF) as f32 * shade) as u32;
        let blue = ((color & 0xFF) as f32 * shade) as u32;

        (red << 16) | (green << 8) | blue
    }
}
