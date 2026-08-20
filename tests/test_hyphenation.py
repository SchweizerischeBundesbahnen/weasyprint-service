"""Tests for the German hyphenation dictionary shipped in the image.

The image replaces Pyphen's bundled German dictionary (LibreOffice, 2017-01-12)
with the newer dehyph-exptl patterns (dehyphn-x 2024-02-28). These tests pin the
concrete hyphenation improvements the update brings.
"""

from pathlib import Path

import pyphen
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DIC_FILE = REPO_ROOT / "dictionaries" / "hyph_de_dehyphn-x-2024-02-28.dic"


@pytest.fixture(scope="module")
def de_dic() -> pyphen.Pyphen:
    return pyphen.Pyphen(filename=str(DIC_FILE))


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        # These were mis-hyphenated by the 2017 LibreOffice dictionary,
        # which broke off a single letter. dehyphn-x 2024 fixes them.
        ("Übergangsbestimmung", "Über-gangs-be-stim-mung"),
        ("Fußgängerübergang", "Fuß-gän-ger-über-gang"),
        ("Billettautomat", "Bil-lett-au-to-mat"),
    ],
)
def test_fixed_hyphenations(de_dic, word, expected):
    assert de_dic.inserted(word, hyphen="-") == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        # Regression guard: common words must still hyphenate sensibly.
        ("Silbentrennung", "Sil-ben-tren-nung"),
        ("Fahrplan", "Fahr-plan"),
        ("Eisenbahn", "Ei-sen-bahn"),
        ("Krankenversicherung", "Kran-ken-ver-si-che-rung"),
    ],
)
def test_common_words_unchanged(de_dic, word, expected):
    assert de_dic.inserted(word, hyphen="-") == expected


def test_no_single_letter_fragments(de_dic):
    """No hyphenated fragment should be a single letter for these words."""
    for word in ("Übergang", "Ausgang", "Zugang", "Eingang", "Übergangsregelung"):
        parts = de_dic.inserted(word, hyphen="-").split("-")
        assert all(len(part) >= 2 for part in parts), (word, parts)
