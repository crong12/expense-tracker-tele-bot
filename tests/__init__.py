"""Focused test bootstrap that avoids application package side effects.

The production ``handlers`` initializer imports cloud-backed services. These
unit tests target handler submodules directly, so expose the real handlers
directory as a namespace package. Python still loads every requested submodule
from its real source file; only ``handlers/__init__.py`` is intentionally not
executed.
"""

from .handler_test_bootstrap import ensure_focused_handlers_package


ensure_focused_handlers_package()
