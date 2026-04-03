pub struct Framebuffer {
    pub width: usize,
    pub height: usize,
    pixels: Vec<u32>,
}

impl Framebuffer {
    pub fn new(width: usize, height: usize) -> Self {
        Self {
            width,
            height,
            pixels: vec![0; width * height],
        }
    }

    pub fn clear(&mut self, color: u32) {
        self.pixels.fill(color);
    }

    pub fn set_pixel(&mut self, x: usize, y: usize, color: u32) {
        if x >= self.width || y >= self.height {
            return;
        }

        let index = y * self.width + x;
        self.pixels[index] = color;
    }

    pub fn fill_rect(&mut self, x: usize, y: usize, width: usize, height: usize, color: u32) {
        if x >= self.width || y >= self.height {
            return;
        }

        let end_x = (x + width).min(self.width);
        let end_y = (y + height).min(self.height);

        for row in y..end_y {
            let start = row * self.width + x;
            let end = row * self.width + end_x;
            self.pixels[start..end].fill(color);
        }
    }

    pub fn draw_vertical_line(&mut self, x: usize, start: i32, end: i32, color: u32) {
        if x >= self.width {
            return;
        }

        let start = start.clamp(0, self.height as i32);
        let end = end.clamp(0, self.height as i32);

        for y in start..end {
            self.set_pixel(x, y as usize, color);
        }
    }

    pub fn draw_line(&mut self, mut x0: i32, mut y0: i32, x1: i32, y1: i32, color: u32) {
        let dx = (x1 - x0).abs();
        let sx = if x0 < x1 { 1 } else { -1 };
        let dy = -(y1 - y0).abs();
        let sy = if y0 < y1 { 1 } else { -1 };
        let mut error = dx + dy;

        loop {
            if x0 >= 0 && y0 >= 0 {
                self.set_pixel(x0 as usize, y0 as usize, color);
            }

            if x0 == x1 && y0 == y1 {
                break;
            }

            let doubled_error = error * 2;
            if doubled_error >= dy {
                error += dy;
                x0 += sx;
            }
            if doubled_error <= dx {
                error += dx;
                y0 += sy;
            }
        }
    }

    pub fn pixels(&self) -> &[u32] {
        &self.pixels
    }

    pub fn to_rgba_bytes(&self) -> Vec<u8> {
        let mut rgba = Vec::with_capacity(self.pixels.len() * 4);

        for pixel in &self.pixels {
            rgba.push(((pixel >> 16) & 0xFF) as u8);
            rgba.push(((pixel >> 8) & 0xFF) as u8);
            rgba.push((pixel & 0xFF) as u8);
            rgba.push(0xFF);
        }

        rgba
    }
}
