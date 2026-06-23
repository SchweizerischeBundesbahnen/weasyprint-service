# Repro: WeasyPrint 69.0 drops `linear-gradient` backgrounds under PDF/A

A CSS `linear-gradient` background renders fine in **WeasyPrint 68.1** but
**disappears in WeasyPrint 69.0** when the PDF is written as **PDF/A**.

* `gradient.html` — minimal input: a single `<div>` with a `linear-gradient` background.
* `repro.py` — renders it with `write_pdf(pdf_variant="pdf/a-2b")`, reports the gradient
  shading's colour space and whether the gradient actually paints, and saves the PDF.
* `run.sh` — runs `repro.py` with both WeasyPrint versions via `uv`.

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

```
weasyprint 68.1 : gradient shading ColorSpace = /DeviceRGB  ->  RENDERED ok
weasyprint 69.0 : gradient shading ColorSpace = /srgb       ->  BLANK (gradient dropped)
```

Open the two saved `gradient_pdfa_*.pdf` files to see it: the gradient box is present
with 68.1 and blank with 69.0.

## Root cause

WeasyPrint 69.0 reworked PDF colour management (output intents / ICC profiles —
Kozea/WeasyPrint #2631, #2778, #2785, #2788). For PDF/A it now expresses colours in a
**named** ICCBased colour space `/srgb` (the output-intent profile). The gradient's
*shading* object gets `ColorSpace /srgb` instead of `/DeviceRGB`. Common PDF rasterisers
— pdfium / MuPDF (PyMuPDF), Apache PDFBox — do not resolve the named `/srgb` colour space
for shadings (`unknown colorspace: srgb`), so the gradient is not painted. WeasyPrint 68.1
used `/DeviceRGB` directly, which every renderer handles.
