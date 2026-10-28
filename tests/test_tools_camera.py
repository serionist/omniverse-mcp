"""The camera tools' text for the AI: warnings and advice, from canned bridge answers."""

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
