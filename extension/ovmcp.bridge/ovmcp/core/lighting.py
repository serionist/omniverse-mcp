"""Which viewport lighting mode is in effect, and what the legacy camera-light switch sets: no Kit."""


def current_mode(camera_light_flag: bool, menu_mode: str | None) -> str:
    """The renderer's camera-light flag is the truth for "camera"; otherwise the lighting menu's mode, or "stage".

    The menu keeps its own record, which goes stale when a script or an older bridge sets the flag directly.
    """
    if camera_light_flag:
        return "camera"
    if not menu_mode or menu_mode == "camera":
        return "stage"
    return menu_mode


def camera_light_switch(enabled: bool, current: str) -> str | None:
    """The mode set_camera_light sets, or None to only clear the camera-light flag and leave a rig alone."""
    if enabled:
        return "camera"
    return "stage" if current == "camera" else None
