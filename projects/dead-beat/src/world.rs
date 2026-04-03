const DEFAULT_WALL_TEXTS: [&str; 4] = [
    "Start from here and if",
    "you turn away from",
    "then end.",
    "Repeat. Repeat.",
];
const TEXT_ROWS_PER_WALL: usize = 4;
const CHARS_PER_TILE: usize = 4;
const ROOM_INNER_WIDTH: usize = 10;
const ROOM_INNER_HEIGHT: usize = 10;

#[derive(Clone, Copy)]
pub enum WallFace {
    North,
    East,
    South,
    West,
}

impl WallFace {
    pub fn index(self) -> usize {
        match self {
            Self::North => 0,
            Self::East => 1,
            Self::South => 2,
            Self::West => 3,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::North => "North",
            Self::East => "East",
            Self::South => "South",
            Self::West => "West",
        }
    }

    fn ordered() -> [Self; 4] {
        [Self::North, Self::East, Self::South, Self::West]
    }
}

pub struct World {
    pub width: usize,
    pub height: usize,
    inner_width: usize,
    inner_height: usize,
    wall_inputs: [String; 4],
    truncated: [bool; 4],
    tiles: Vec<u8>,
    wall_text_lines: [Vec<String>; 4],
}

impl World {
    pub fn demo() -> Self {
        Self::from_wall_inputs([
            DEFAULT_WALL_TEXTS[0].to_string(),
            DEFAULT_WALL_TEXTS[1].to_string(),
            DEFAULT_WALL_TEXTS[2].to_string(),
            DEFAULT_WALL_TEXTS[3].to_string(),
        ])
    }

    pub fn from_wall_inputs(wall_inputs: [String; 4]) -> Self {
        let (wall_text_lines, truncated) = layout_room(&wall_inputs);
        let width = ROOM_INNER_WIDTH + 2;
        let height = ROOM_INNER_HEIGHT + 2;

        let mut world = Self {
            width,
            height,
            inner_width: ROOM_INNER_WIDTH,
            inner_height: ROOM_INNER_HEIGHT,
            wall_inputs,
            truncated,
            tiles: vec![0; width * height],
            wall_text_lines,
        };

        world.build_outer_walls();
        world.add_islands();
        world
    }

    pub fn spawn_point(&self) -> (f32, f32) {
        ((self.width as f32) * 0.5, (self.height as f32) * 0.5)
    }

    pub fn is_wall(&self, x: usize, y: usize) -> bool {
        if x >= self.width || y >= self.height {
            return true;
        }

        self.tiles[y * self.width + x] != 0
    }

    pub fn is_wall_at(&self, x: f32, y: f32) -> bool {
        if x < 0.0 || y < 0.0 {
            return true;
        }

        self.is_wall(x.floor() as usize, y.floor() as usize)
    }

    pub fn wall_face_for_hit(
        &self,
        tile_x: usize,
        tile_y: usize,
        hit_vertical: bool,
    ) -> Option<WallFace> {
        if hit_vertical {
            if tile_x == 0 {
                Some(WallFace::West)
            } else if tile_x + 1 == self.width {
                Some(WallFace::East)
            } else {
                None
            }
        } else if tile_y == 0 {
            Some(WallFace::North)
        } else if tile_y + 1 == self.height {
            Some(WallFace::South)
        } else {
            None
        }
    }

    pub fn wall_u(&self, face: WallFace, hit_x: f32, hit_y: f32) -> Option<f32> {
        let width = self.inner_width.max(1) as f32;
        let height = self.inner_height.max(1) as f32;

        match face {
            WallFace::North => {
                if !(1.0..(self.inner_width as f32 + 1.0)).contains(&hit_x) {
                    return None;
                }
                Some(((hit_x - 1.0) / width).clamp(0.0, 0.999))
            }
            WallFace::South => {
                if !(1.0..(self.inner_width as f32 + 1.0)).contains(&hit_x) {
                    return None;
                }
                Some((1.0 - ((hit_x - 1.0) / width)).clamp(0.0, 0.999))
            }
            WallFace::East => {
                if !(1.0..(self.inner_height as f32 + 1.0)).contains(&hit_y) {
                    return None;
                }
                Some(((hit_y - 1.0) / height).clamp(0.0, 0.999))
            }
            WallFace::West => {
                if !(1.0..(self.inner_height as f32 + 1.0)).contains(&hit_y) {
                    return None;
                }
                Some((1.0 - ((hit_y - 1.0) / height)).clamp(0.0, 0.999))
            }
        }
    }

    pub fn wall_lines(&self, face: WallFace) -> &[String] {
        &self.wall_text_lines[face.index()]
    }

    pub fn wall_input(&self, face: WallFace) -> &str {
        &self.wall_inputs[face.index()]
    }

    pub fn wall_span_tiles(&self, face: WallFace) -> usize {
        match face {
            WallFace::North | WallFace::South => self.inner_width,
            WallFace::East | WallFace::West => self.inner_height,
        }
    }

    pub fn debug_layout(&self) -> String {
        let mut out = String::new();

        for face in WallFace::ordered() {
            out.push_str(face.label());
            if self.truncated[face.index()] {
                out.push_str(" (truncated)");
            }
            out.push('\n');

            for line in self.wall_lines(face) {
                if line.is_empty() {
                    out.push_str("  [empty]\n");
                } else {
                    out.push_str("  ");
                    out.push_str(line);
                    out.push('\n');
                }
            }

            out.push('\n');
        }

        out.push_str("Room ");
        out.push_str(&self.width.to_string());
        out.push('x');
        out.push_str(&self.height.to_string());

        out
    }

    fn build_outer_walls(&mut self) {
        for x in 0..self.width {
            self.set_wall(x, 0);
            self.set_wall(x, self.height - 1);
        }

        for y in 0..self.height {
            self.set_wall(0, y);
            self.set_wall(self.width - 1, y);
        }
    }

    fn add_islands(&mut self) {
        let islands = [
            (self.width / 4, self.height / 4, 2, 1),
            (self.width * 2 / 3, self.height / 3, 2, 1),
            (self.width / 3, self.height * 2 / 3, 1, 1),
            (self.width * 3 / 4, self.height * 3 / 4, 1, 1),
        ];

        for (x, y, width, height) in islands {
            self.stamp_island(x, y, width, height);
        }
    }

    fn set_wall(&mut self, x: usize, y: usize) {
        self.tiles[y * self.width + x] = 1;
    }

    fn stamp_island(&mut self, x: usize, y: usize, width: usize, height: usize) {
        let start_x = x.clamp(2, self.width.saturating_sub(width + 2));
        let start_y = y.clamp(2, self.height.saturating_sub(height + 2));

        for row in start_y..(start_y + height).min(self.height - 1) {
            for col in start_x..(start_x + width).min(self.width - 1) {
                self.set_wall(col, row);
            }
        }
    }
}

fn layout_room(wall_inputs: &[String; 4]) -> ([Vec<String>; 4], [bool; 4]) {
    let north = wrap_wall(
        &wall_inputs[WallFace::North.index()],
        ROOM_INNER_WIDTH * CHARS_PER_TILE,
    );
    let east = wrap_wall(
        &wall_inputs[WallFace::East.index()],
        ROOM_INNER_HEIGHT * CHARS_PER_TILE,
    );
    let south = wrap_wall(
        &wall_inputs[WallFace::South.index()],
        ROOM_INNER_WIDTH * CHARS_PER_TILE,
    );
    let west = wrap_wall(
        &wall_inputs[WallFace::West.index()],
        ROOM_INNER_HEIGHT * CHARS_PER_TILE,
    );

    (
        [north.0, east.0, south.0, west.0],
        [north.1, east.1, south.1, west.1],
    )
}

fn wrap_wall(text: &str, max_chars: usize) -> (Vec<String>, bool) {
    let mut lines = wrap_text(text, max_chars);
    let truncated = lines.len() > TEXT_ROWS_PER_WALL;
    lines.truncate(TEXT_ROWS_PER_WALL);

    while lines.len() < TEXT_ROWS_PER_WALL {
        lines.push(String::new());
    }

    (lines, truncated)
}

fn wrap_text(text: &str, max_chars: usize) -> Vec<String> {
    if text.trim().is_empty() || max_chars == 0 {
        return Vec::new();
    }

    let mut lines = Vec::new();
    let mut current = String::new();

    for word in text.split_whitespace() {
        for segment in split_long_word(word, max_chars) {
            let segment_len = segment.chars().count();
            let current_len = current.chars().count();
            let proposed_len = if current.is_empty() {
                segment_len
            } else {
                current_len + 1 + segment_len
            };

            if proposed_len <= max_chars {
                if !current.is_empty() {
                    current.push(' ');
                }
                current.push_str(&segment);
            } else {
                lines.push(current);
                current = segment;
            }
        }
    }

    if !current.is_empty() {
        lines.push(current);
    }

    lines
}

fn split_long_word(word: &str, max_chars: usize) -> Vec<String> {
    if word.chars().count() <= max_chars {
        return vec![word.to_string()];
    }

    let mut parts = Vec::new();
    let mut current = String::new();

    for ch in word.chars() {
        current.push(ch);

        if current.chars().count() == max_chars {
            parts.push(current);
            current = String::new();
        }
    }

    if !current.is_empty() {
        parts.push(current);
    }

    parts
}
