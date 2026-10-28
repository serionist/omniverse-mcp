# Kit imports this package and instantiates the Extension it finds. Outside Kit (the core's unit tests) there is
# no omni, and only isaacsim.mcp.bridge.core is used.
try:
    import omni.ext  # noqa: F401
except ImportError:
    pass
else:
    from .extension import Extension  # noqa: F401
