"""The camera tools' text for the AI: warnings and advice, from canned bridge answers."""

import pytest

from isaac_sim_mcp.tools import camera


class _Tools:
    """Stands in for the MCP server: keeps the functions register() decorates."""

    def __init__(self):
        self.fns = {}

    def tool(self, **_kwargs):
        def keep(fn):
            self.fns[fn.__name__] = fn
            return fn

        return keep


class _Helpers:
    def __init__(self, tmp_path):
        self.output_dir = str(tmp_path)
        self.capture_counter = 0

    def save_png(self, _b64, prefix="capture"):
        self.capture_counter += 1
        return f"mcp_output/captures/{prefix}_{self.capture_counter:04d}.png"

    def rel(self, path):
        return path


class _Client:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.answers[name]

        return call


def _tools(tmp_path, answers):
    tools, client = _Tools(), _Client(answers)
    camera.register(tools, client, _Helpers(tmp_path))
    return tools.fns, client


def _inspect_answer(**extra):
    capture = {"angle": "front", "azimuth": 0, "elevation": 0, "camera_position": [0, 0, 5],
               "image_base64": "iVBORw0KGgo=", "is_black": extra.pop("is_black", False)}
    result = {"prim_path": "/World/Lamp", "center": [0, 0, 0], "distance": 5.0, "zoom_offset": 0.0,
              "isolate": False, "isolate_warnings": [], "captures": [capture]}
    result.update(extra)
    return {"status": "success", "result": result}


def test_inspect_prints_the_isolate_warnings(tmp_path):
    warning = "/World/Lamp is an instance that holds a light; children of an instance can't be hidden"
    fns, _ = _tools(tmp_path, {"camera_inspect": _inspect_answer(isolate=True, isolate_warnings=[warning])})
    out = fns["inspect_prim"]("/World/Lamp", isolate=True)
    assert f"WARNING (isolate): {warning}" in out


def _capture_answer(lighting_mode, has_scene_lights):
    return {"status": "success", "result": {
        "image_base64": "iVBORw0KGgo=", "width": 1280, "height": 720, "camera_path": "/OmniverseKit_Persp",
        "format": "png", "is_black": True, "lighting_mode": lighting_mode, "has_scene_lights": has_scene_lights,
        "screen_bboxes": [], "segmentation_base64": None, "segmentation_legend": {},
    }}


@pytest.mark.parametrize(("mode", "lights"), [("off", True), ("stage", False), ("Default", True)])
def test_a_black_capture_suggests_camera_mode_first(tmp_path, mode, lights):
    fns, _ = _tools(tmp_path, {"capture_viewport": _capture_answer(mode, lights)})
    out = fns["capture_viewport"]()
    assert "viewport_light(action='set', mode='camera')" in out
    assert "mode='Default' if viewport_light('get') lists it" in out


def test_a_black_inspect_gives_the_same_advice(tmp_path):
    fns, _ = _tools(tmp_path, {"camera_inspect": _inspect_answer(is_black=True)})
    out = fns["inspect_prim"]("/World/Lamp")
    assert "viewport_light(action='set', mode='camera')" in out
    assert "enable camera light" not in out
    assert "isolate" not in out


def test_a_black_isolated_inspect_says_what_isolate_hid(tmp_path):
    fns, _ = _tools(tmp_path, {"camera_inspect": _inspect_answer(is_black=True, isolate=True)})
    out = fns["inspect_prim"]("/World/Lamp", isolate=True)
    assert "viewport_light(action='set', mode='camera')" in out
    assert "hid the other prims, though not the lights" in out


@pytest.mark.parametrize("action", ["set", "set_camera_light"])
def test_viewport_light_reports_the_resulting_mode(tmp_path, action):
    answer = {"status": "success", "result": {"lighting_mode": "Default",
                                              "message": "Viewport camera light turned off; the lighting mode is unchanged"}}
    fns, client = _tools(tmp_path, {"viewport_light": answer})
    out = fns["viewport_light"](action=action, mode="Default", enabled=False)
    assert out.splitlines() == ["Lighting mode: Default", answer["result"]["message"]]
    assert client.calls == [("viewport_light", (action, False), {"mode": "Default"})]


def test_a_black_capture_with_the_camera_light_on_does_not_suggest_it_again(tmp_path):
    fns, _ = _tools(tmp_path, {"capture_viewport": _capture_answer("camera", False)})
    out = fns["capture_viewport"]()
    assert "mode='camera'" not in out
    assert "camera light is already on" in out
    assert "look_at_prim" in out


def test_a_black_inspect_with_the_camera_light_on_does_not_suggest_it_again(tmp_path):
    fns, _ = _tools(tmp_path, {"camera_inspect": _inspect_answer(is_black=True, lighting_mode="camera")})
    out = fns["inspect_prim"]("/World/Lamp")
    assert "mode='camera'" not in out
    assert "look_at_prim" in out
