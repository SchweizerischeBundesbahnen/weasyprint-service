"""Work around a WeasyPrint crash on a running element inside a shrink-to-fit box.

Background
----------
A block-level ``position: running(name)`` element that holds text raises
``TypeError: min-content width for TextBox not handled yet`` when it sits inside
an intrinsic-width (shrink-to-fit) container: a float, an ``inline-block``, an
absolutely positioned box, an auto-layout table cell or a flex item.

Two WeasyPrint details combine into the crash:

1. ``formatting_structure/build.py`` returns early from ``inline_in_block()`` for
   a running box, so its text is never wrapped in a ``LineBox`` and a bare
   ``TextBox`` survives as a direct child of the block.
2. ``layout/preferred.py`` filters only absolutely positioned children out of the
   intrinsic-width walk, so it recurses into the running box, reaches that
   ``TextBox`` and has no branch for it.

The ``@page { @top-center { content: element(name) } }`` rule that normally
consumes the running element is not required to trigger the crash.

Fix
---
A running element is removed from the normal flow (see ``Box.is_in_normal_flow``),
so it must not contribute to the intrinsic width of its container at all. Return
zero for a running box at every entry point of the intrinsic-width calculation.

This is a temporary shim. ``apply_running_width_patch`` is idempotent and, if a
future WeasyPrint no longer exposes the patched internals, degrades to a no-op
without ever breaking PDF generation. Remove it once fixed upstream.
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_running_element_width_patch"


def _layout_module(name: str) -> Any | None:
    """Import a private WeasyPrint layout module, or return ``None``.

    These modules are internal to WeasyPrint. Importing them by hand keeps the
    no-op promise of this shim honest: a future WeasyPrint that moves or drops
    one must not stop the service from starting.
    """
    try:
        return importlib.import_module(f"weasyprint.layout.{name}")
    except ImportError:
        logger.warning("WeasyPrint layout module %r not found; running-element patch degraded", name, exc_info=True)
        return None


weasyprint_preferred = _layout_module("preferred")

# Intrinsic-width entry points of weasyprint.layout.preferred, with the value a
# running box must contribute. The table-cell helpers are patched too because
# weasyprint.layout.table reaches them without going through min_content_width.
_PATCHED_FUNCTIONS: dict[str, Any] = {
    "min_content_width": 0,
    "max_content_width": 0,
    "table_cell_min_content_width": 0,
    "table_cell_min_max_content_width": (0, 0),
}

# Modules that bind min_content_width/max_content_width by name at import time.
# Patching weasyprint.layout.preferred alone would leave their copies unpatched.
_MIRROR_MODULES = tuple(module for module in (_layout_module("flex"), _layout_module("grid"), _layout_module("page")) if module is not None)
_MIRRORED_NAMES = ("min_content_width", "max_content_width")


def _zero_for_running(function: Callable[..., Any], empty: Any) -> Callable[..., Any]:
    """Wrap an intrinsic-width function so a running box contributes ``empty``."""
    warned = False

    def wrapper(context: Any, box: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal warned
        try:
            is_running = box.is_running()
        except Exception:
            # This branch means the box API changed, so every box takes it. Warn once
            # per wrapper instead of once per box, or one conversion floods the log.
            if not warned:
                warned = True
                logger.warning("Running-element width patch skipped for one box; suppressing further warnings", exc_info=True)
            is_running = False
        if is_running:
            return empty
        return function(context, box, *args, **kwargs)

    setattr(wrapper, _PATCH_FLAG, True)
    return wrapper


def apply_running_width_patch() -> bool:
    """Monkey-patch WeasyPrint so a running element has no intrinsic width.

    Returns ``True`` when the patch is applied, ``False`` when it was already
    applied or the WeasyPrint internals could not be located.
    """
    if weasyprint_preferred is None or is_applied():
        return False

    originals: dict[str, Any] = {}
    missing: list[str] = []
    for name in _PATCHED_FUNCTIONS:
        function = getattr(weasyprint_preferred, name, None)
        if function is None:
            missing.append(name)
        else:
            originals[name] = function
    if missing:
        logger.warning("WeasyPrint intrinsic-width functions not found (%s); running-element patch skipped", ", ".join(missing))
        return False

    for name, empty in _PATCHED_FUNCTIONS.items():
        setattr(weasyprint_preferred, name, _zero_for_running(originals[name], empty))
    for module in _MIRROR_MODULES:
        for name in _MIRRORED_NAMES:
            if hasattr(module, name):
                setattr(module, name, getattr(weasyprint_preferred, name))

    logger.info("Applied WeasyPrint running-element intrinsic-width patch (running boxes no longer contribute a width)")
    return True


def is_applied() -> bool:
    """Return whether the running-element intrinsic-width patch is installed."""
    return all(getattr(getattr(weasyprint_preferred, name, None), _PATCH_FLAG, False) for name in _PATCHED_FUNCTIONS)
