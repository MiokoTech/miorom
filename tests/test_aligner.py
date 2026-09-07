import pytest
from miorom.text.aligner import StringAligner, AlignedString


def test_string_aligner_exact_and_shifted():
    # Version A (e.g. Japanese or v1.0)
    strings_a = [
        "Good morning, hero!",
        "Take this sword.",
        "Beware of the goblins in the dark woods.",
        "Farewell!",
    ]
    pointers_a = [0x1000, 0x1020, 0x1040, 0x1080]

    # Version B (e.g. Revised / US release with an added tutorial line)
    strings_b = [
        "Good morning, hero!",
        "Take this sword.",
        "Press A to swing your sword.", # Inserted line in B!
        "Beware of the goblins in the dark woods.",
        "Farewell!",
    ]
    pointers_b = [0x2000, 0x2020, 0x2040, 0x2060, 0x20A0]

    alignment = StringAligner.align(
        strings_a=strings_a,
        strings_b=strings_b,
        pointers_a=pointers_a,
        pointers_b=pointers_b,
    )

    # Check alignment count (4 aligned, 1 inserted in B)
    assert len(alignment) == 5

    # Check that "Good morning, hero!" matches exactly
    assert alignment[0].string_a == "Good morning, hero!"
    assert alignment[0].string_b == "Good morning, hero!"
    assert alignment[0].similarity == 1.0

    # Check inserted line
    assert alignment[2].index_a is None
    assert alignment[2].string_b == "Press A to swing your sword."
    assert alignment[2].is_orphan_b is True

    # Check that subsequent strings aligned correctly despite the shift!
    assert alignment[3].string_a == "Beware of the goblins in the dark woods."
    assert alignment[3].string_b == "Beware of the goblins in the dark woods."
    assert alignment[4].string_a == "Farewell!"
    assert alignment[4].string_b == "Farewell!"

    # Test transfer translations
    translations_a = {
        0: "Selamat pagi, pahlawan!",
        1: "Ambil pedang ini.",
        2: "Waspadalah terhadap goblin di hutan gelap.",
        3: "Sampai jumpa!",
    }
    transferred = StringAligner.transfer_translations(alignment, translations_a, by_pointer=False)

    # 0 -> 0, 1 -> 1, 2 -> 3 (shifted by inserted row!), 3 -> 4
    assert transferred[0] == "Selamat pagi, pahlawan!"
    assert transferred[1] == "Ambil pedang ini."
    assert transferred[3] == "Waspadalah terhadap goblin di hutan gelap."
    assert transferred[4] == "Sampai jumpa!"
    assert 2 not in transferred # The inserted line has no source translation
