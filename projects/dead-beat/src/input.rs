#[derive(Clone, Copy, Debug, Default)]
pub struct InputState {
    pub forward: bool,
    pub backward: bool,
    pub turn_left: bool,
    pub turn_right: bool,
    pub strafe_left: bool,
    pub strafe_right: bool,
}
