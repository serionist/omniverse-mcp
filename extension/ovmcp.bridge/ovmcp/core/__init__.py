"""The bridge's Kit-free core.

Nothing here imports omni, carb or isaacsim, so the unit tests run it without a Kit app; import-linter holds that
(pyproject.toml). bounds, formatter, isolation and usd import pxr, which the tests get from usd-core; png imports
numpy, which Kit ships and the dev group adds.
"""
