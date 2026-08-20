# German hyphenation dictionaries

WeasyPrint hyphenates via [Pyphen](https://pyphen.org/), which ships the
LibreOffice hyphenation dictionaries. The bundled German dictionaries
(`hyph_de_DE.dic`, `hyph_de_AT.dic`, `hyph_de_CH.dic`) are frozen at
**2017-01-12** and contain known defects, e.g. they break a single letter off
compounds: `Über-g-ang`, `Fuß-gän-ger-über-g-ang`, `Bil-let-t-au-to-mat`.

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
| License | MIT — see [`LICENSE.dehyph-exptl`](LICENSE.dehyph-exptl) (shipped in the image next to the data) |

The `.dic` is the `dehyphn-x` TeX patterns converted to the Hunspell format
Pyphen consumes (the TeX `\patterns{ ... }` wrapper removed and an encoding
line prepended). At image build time it is copied over `hyph_de_DE.dic`,
`hyph_de_AT.dic` and `hyph_de_CH.dic` (see `Dockerfile`).

`dehyphn-x` is the reformed-orthography set covering Germany, Austria and
Switzerland, so it is used for all three locales — consistent with the reformed
orthography the service already relies on. Note that Swiss German writes `ss`
where Germany/Austria write `ß`; patterns containing `ß` simply never match
Swiss text, so reusing the reformed set for `de_CH` is safe (it replaces a
`de_CH` dictionary that was already the reformed German set).
