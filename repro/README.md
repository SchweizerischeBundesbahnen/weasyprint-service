# Repro: WeasyPrint 69.0 drops `linear-gradient` backgrounds under PDF/A

A CSS `linear-gradient` background renders fine in **WeasyPrint 68.1** but
**disappears in WeasyPrint 69.0** when the PDF is written as **PDF/A**.

* `gradient.html` — minimal input: a single `<div>` with a `linear-gradient` background.
* `repro.py` — renders it with `write_pdf(pdf_variant="pdf/a-2b")`, reports the gradient
  shading's colour space and whether the gradient actually paints, and saves the PDF.
  Pass `--patch` to apply the service workaround (`app/weasyprint_pdfa_patch.py`).
* `run.sh` — runs `repro.py` with WeasyPrint 68.1, 69.0, and 69.0 + the fix, via `uv`.

## Run (native, no Docker)

Prerequisites: [`uv`](https://docs.astral.sh/uv/) and WeasyPrint's system libraries.

```bash
# macOS (one-time): install the native libs WeasyPrint needs
brew install pango          # pulls glib/gobject, cairo, harfbuzz, fontconfig, …

./run.sh
```

On Linux: `apt-get install libpango-1.0-0 libpangocairo-1.0-0`, then `./run.sh`.

Run a single version manually (macOS needs `DYLD_FALLBACK_LIBRARY_PATH` so dlopen finds
Homebrew's libs):

```bash
DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib" \
  uv run --with 'weasyprint==69.0' --with pymupdf repro.py
```

## Expected output

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

## Validating on a future WeasyPrint version

When bumping WeasyPrint, run the repro on the new version with and without the fix:

```bash
uv run --with 'weasyprint==<new>' --with pymupdf repro.py            # without the patch
uv run --with 'weasyprint==<new>' --with pymupdf repro.py --patch    # with the patch
```

* without `--patch` **RENDERED** → upstream fixed it; the service patch can be removed.
* without `--patch` **BLANK** but with `--patch` **RENDERED** → keep the patch.
* with `--patch` **BLANK** → WeasyPrint internals changed; the patch needs updating
  (it fails safe — never breaks PDF generation — but no longer fixes the gradient).

## Root cause

WeasyPrint 69.0 reworked PDF colour management (output intents / ICC profiles —
Kozea/WeasyPrint #2631, #2778, #2785, #2788). For PDF/A it now expresses colours in a
**named** ICCBased colour space `/srgb` (the output-intent profile). The gradient's
*shading* object gets `ColorSpace /srgb` instead of `/DeviceRGB`. Common PDF rasterisers
— pdfium / MuPDF (PyMuPDF), Apache PDFBox — do not resolve the named `/srgb` colour space
for shadings (`unknown colorspace: srgb`), so the gradient is not painted. WeasyPrint 68.1
used `/DeviceRGB` directly, which every renderer handles.
