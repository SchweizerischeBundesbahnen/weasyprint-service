# WeasyPrint bug reproductions

Minimal, service-free reproductions of the upstream WeasyPrint bugs that `app/` works
around. Each one runs the same monkey patch the service applies, so a WeasyPrint bump can
be checked against them before the workaround is kept or dropped.

| Repro | Bug | Service workaround |
|---|---|---|
| [PDF/A gradients](#1-weasyprint-690-drops-linear-gradient-backgrounds-under-pdfa) | `linear-gradient` disappears from PDF/A output | `app/weasyprint_pdfa_patch.py` |
| [Running elements](#2-weasyprint-crashes-on-a-running-element-in-a-shrink-to-fit-box) | `TypeError: min-content width for TextBox not handled yet` | `app/weasyprint_running_width_patch.py` |

## Run (native, no Docker)

Prerequisites: [`uv`](https://docs.astral.sh/uv/) and WeasyPrint's system libraries.

```bash
# macOS (one-time): install the native libs WeasyPrint needs
brew install pango          # pulls glib/gobject, cairo, harfbuzz, fontconfig, …

./run.sh                    # runs both reproductions
```

On Linux: `apt-get install libpango-1.0-0 libpangocairo-1.0-0`, then `./run.sh`.

Run a single repro manually (macOS needs `DYLD_FALLBACK_LIBRARY_PATH` so dlopen finds
Homebrew's libs):

```bash
DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib" \
  uv run --with 'weasyprint==69.0' --with pymupdf repro.py
```

---

## 1. WeasyPrint 69.0 drops `linear-gradient` backgrounds under PDF/A

A CSS `linear-gradient` background renders fine in **WeasyPrint 68.1** but
**disappears in WeasyPrint 69.0** when the PDF is written as **PDF/A**.

* `gradient.html` — minimal input: a single `<div>` with a `linear-gradient` background.
* `repro.py` — renders it with `write_pdf(pdf_variant="pdf/a-2b")`, reports the gradient
  shading's colour space and whether the gradient actually paints, and saves the PDF.
  Pass `--patch` to apply the service workaround (`app/weasyprint_pdfa_patch.py`).

### Expected output

Each run reports every supported PDF/A variant. On WeasyPrint 69.0:

```
weasyprint 69.0
  pdf/a-1b  shading ColorSpace = /srgb              ->  BLANK (gradient dropped)
  pdf/a-1a  shading ColorSpace = /srgb              ->  BLANK (gradient dropped)
  ...                                                    (all 11 variants BLANK)
  pdf/a-4f  shading ColorSpace = /srgb              ->  BLANK (gradient dropped)

weasyprint 69.0+patch
  pdf/a-1b  shading ColorSpace = [/ICCBased 3 0 R]  ->  RENDERED ok
  ...                                                    (all 11 variants RENDERED)
  pdf/a-4f  shading ColorSpace = [/ICCBased 3 0 R]  ->  RENDERED ok
```

On WeasyPrint 68.1 every variant renders (`ColorSpace = /DeviceRGB`). A representative
`gradient_pdf-a-2b_*.pdf` is saved per run for visual inspection.

### Validating on a future WeasyPrint version

When bumping WeasyPrint, run the repro on the new version with and without the fix:

```bash
uv run --with 'weasyprint==<new>' --with pymupdf repro.py            # without the patch
uv run --with 'weasyprint==<new>' --with pymupdf repro.py --patch    # with the patch
```

* without `--patch` **RENDERED** → upstream fixed it; the service patch can be removed.
* without `--patch` **BLANK** but with `--patch` **RENDERED** → keep the patch.
* with `--patch` **BLANK** → WeasyPrint internals changed; the patch needs updating
  (it fails safe — never breaks PDF generation — but no longer fixes the gradient).

### Root cause

WeasyPrint 69.0 reworked PDF colour management (output intents / ICC profiles —
Kozea/WeasyPrint #2631, #2778, #2785, #2788). For PDF/A it now expresses colours in a
**named** ICCBased colour space `/srgb` (the output-intent profile). The gradient's
*shading* object gets `ColorSpace /srgb` instead of `/DeviceRGB`. Common PDF rasterisers
— pdfium / MuPDF (PyMuPDF), Apache PDFBox — do not resolve the named `/srgb` colour space
for shadings (`unknown colorspace: srgb`), so the gradient is not painted. WeasyPrint 68.1
used `/DeviceRGB` directly, which every renderer handles.

---

## 2. WeasyPrint crashes on a running element in a shrink-to-fit box

A block-level `position: running(name)` element holding text makes WeasyPrint raise
`TypeError: min-content width for TextBox not handled yet` when it sits inside an
intrinsic-width container. Reproduced on **WeasyPrint 68.1 and 69.0**.

* `running_element.html` — minimal input: a running element inside a `float: left` box.
* `repro_running_element.py` — renders that running element under every intrinsic-width
  wrapper and reports which ones convert. Pass `--patch` to apply the service workaround
  (`app/weasyprint_running_width_patch.py`).

Three ingredients are required. Remove any one and the error disappears.

1. `position: running(name)` on a **block-level** element.
2. **Text** inside it. An empty running element is fine, and so is `position: running()`
   on an inline `<span>`.
3. An **intrinsic-width (shrink-to-fit) wrapper**: `float`, `display: inline-block`,
   `position: absolute`, an auto-layout `<td>`, or a flex item.

The `@page { @top-center { content: element(name) } }` rule that normally consumes the
running element is **not** required. `width: min-content` on the wrapper does not trigger
it either.

### Expected output

```
weasyprint 69.0
  float: left                      ->  CRASHES: TypeError: min-content width for TextBox not handled yet
  ...                                           (every wrapper crashes)
  flex item                        ->  CRASHES: TypeError: min-content width for TextBox not handled yet

weasyprint 69.0+patch
  float: left                      ->  CONVERTS ok (4041 bytes, running text in top margin box)
  ...                                           (every wrapper converts)
  flex item                        ->  CONVERTS ok (4039 bytes, running text in top margin box)
```

`running text in top margin box` confirms the patch costs the running element nothing: its
content still moves into the `@top-center` margin box.

### Validating on a future WeasyPrint version

```bash
uv run --with 'weasyprint==<new>' --with pymupdf repro_running_element.py           # without
uv run --with 'weasyprint==<new>' --with pymupdf repro_running_element.py --patch   # with
```

* without `--patch` every wrapper **CONVERTS** → upstream fixed it; the service patch can
  be removed.
* without `--patch` **CRASHES** but with `--patch` **CONVERTS** → keep the patch.
* with `--patch` **CRASHES** → WeasyPrint internals changed; the patch needs updating
  (it fails safe — never breaks PDF generation — but no longer prevents the crash).

### Root cause

Two WeasyPrint details combine. `formatting_structure/build.py` returns early from
`inline_in_block()` for a running box, so its text is never wrapped in a `LineBox` and a
bare `TextBox` survives as a direct child of the block. `layout/preferred.py` then filters
only absolutely positioned children out of the intrinsic-width walk, recurses into the
running box, reaches that `TextBox` and has no branch for it.

A running element is removed from the normal flow (`Box.is_in_normal_flow()` says so), so
it must not contribute to its container's intrinsic width at all. The patch returns zero
for a running box at every entry point of the intrinsic-width calculation.

Two exotic cases stay broken with the patch, because table and grid layout keep a running
child in the flow and then fail differently (`TypeError: Layout for TextBox not handled
yet`): a `<td>` that is itself the running element, and a running element that is itself a
grid item. Neither produces the error this repro is about.
