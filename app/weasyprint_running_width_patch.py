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

import logging
from typing import TYPE_CHECKING, Any

from weasyprint.layout import flex as weasyprint_flex  # type: ignore[import-untyped]
from weasyprint.layout import grid as weasyprint_grid  # type: ignore[import-untyped]
from weasyprint.layout import page as weasyprint_page  # type: ignore[import-untyped]
from weasyprint.layout import preferred as weasyprint_preferred  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_running_element_width_patch"

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
_MIRROR_MODULES = (weasyprint_flex, weasyprint_grid, weasyprint_page)
_MIRRORED_NAMES = ("min_content_width", "max_content_width")


def _zero_for_running(function: Callable[..., Any], empty: Any) -> Callable[..., Any]:
    """Wrap an intrinsic-width function so a running box contributes ``empty``."""

    def wrapper(context: Any, box: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            is_running = box.is_running()
        except Exception:
            logger.warning("Running-element width patch skipped for one box", exc_info=True)
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
    if is_applied():
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
