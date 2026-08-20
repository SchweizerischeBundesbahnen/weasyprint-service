# German hyphenation dictionaries

WeasyPrint hyphenates via [Pyphen](https://pyphen.org/), which ships the
LibreOffice hyphenation dictionaries. The bundled German dictionary
(`hyph_de_DE.dic` / `hyph_de_CH.dic`) is frozen at **2017-01-12** and contains
known defects, e.g. it breaks a single letter off compounds:
`Über-g-ang`, `Fuß-gän-ger-über-g-ang`, `Bil-let-t-au-to-mat`.

To fix this, the Docker image replaces the bundled German patterns with the
newer, actively maintained **dehyph-exptl** patterns.

## Source

| Item | Value |
|------|-------|
| File | `hyph_de_dehyphn-x-2024-02-28.dic` — Hunspell dictionary used by Pyphen |
| Derived from | `dehyph-exptl` · `dehyphn-x` TeX patterns (reformed orthography 2006; covers DE + AT + CH) |
| Version | 2024-02-28 |
| Upstream | https://ctan.org/pkg/dehyph-exptl |
| Authors | Deutschsprachige Trennmustermannschaft (`trennmuster@dante.de`) |
| License | MIT |

The `.dic` is the `dehyphn-x` TeX patterns converted to the Hunspell format
Pyphen consumes (the TeX `\patterns{ ... }` wrapper removed and an encoding
line prepended). The reformed pattern set is used for both `de_DE` and `de_CH`,
consistent with the reformed orthography already used by the service. At image
build time it is copied over `hyph_de_DE.dic` and `hyph_de_CH.dic` (see
`Dockerfile`).
