"""Focused test bootstrap that avoids application package side effects.

The production ``handlers`` initializer imports cloud-backed services. These
unit tests target handler submodules directly, so expose the real handlers
directory as a namespace package. Python still loads every requested submodule
from its real source file; only ``handlers/__init__.py`` is intentionally not
executed.
"""

import sys
import types
from pathlib import Path


if "handlers" not in sys.modules:
    handlers_package = types.ModuleType("handlers")
    handlers_package.__path__ = [str(Path(__file__).parents[1] / "handlers")]
    handlers_package.__package__ = "handlers"
    sys.modules["handlers"] = handlers_package
