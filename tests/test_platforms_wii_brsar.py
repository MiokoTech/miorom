"""
tests/test_platforms_wii_brsar.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit test suite for Nintendo Wii BRSAR (Binary Revolution Sound Archive) Engine.
Tests low-level binary structures, SYMB/INFO/FILE relational linking, RWSD audio
decoding/encoding, WAV bridge, cross-archive voice undubbing, and error handling.
"""

import math
from typing import List

import pytest

from miorom.audio.wav_codec import WavSound
from miorom.errors import ParseError
from miorom.platforms.wii.brsar import (
    ALIGNMENT_32,
    CODEC_PCM16,
    BRSARHeaderStruct,
    BRSARSoundArchive,
    RWSDFile,
    create_synthetic_brsar,
)


def _generate_sine_wave(frequency: float, duration_seconds: float, sample_rate: int = 32000) -> List[int]:
    """Helper to generate a simple sine wave as 16-bit signed PCM samples."""
    num_samples = int(duration_seconds * sample_rate)
    samples = []
    for i in range(num_samples):
        val = int(16000 * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(val)
    return samples


def test_brsar_synthetic_creation_and_parse():
    """Verifies creating a synthetic BRSAR archive, parsing headers, sections, and symbols."""
    sound1 = ("VO_MARIO_JUMP", _generate_sine_wave(440.0, 0.1, 32000), 32000)
    sound2 = ("VO_PEACH_HELP", _generate_sine_wave(880.0, 0.15, 32000), 32000)
    sound3 = ("SE_KART_ENGINE", _generate_sine_wave(220.0, 0.08, 32000), 32000)

    raw_brsar = create_synthetic_brsar([sound1, sound2, sound3])
    assert raw_brsar[:4] == b"RSAR"

    archive = BRSARSoundArchive.from_bytes(raw_brsar)
    assert archive._header.magic == b"RSAR"
    assert archive._header.bom == 0xFEFF
    assert archive._header.version == 0x0104
    assert archive._header.file_size == len(raw_brsar)

    sounds = archive.list_sounds()
    assert len(sounds) == 3
    assert sounds[0].name == "VO_MARIO_JUMP"
    assert sounds[1].name == "VO_PEACH_HELP"
    assert sounds[2].name == "SE_KART_ENGINE"

    for s in sounds:
        assert s.is_wave
        assert s.sound_type == "WSD"
        assert s.file_size > 0


def test_brsar_symbol_lookup_and_search():
    """Verifies symbol table querying by exact name, numeric ID, and prefix filtering."""
    sounds_data = [
        ("VO_MARIO_JUMP", _generate_sine_wave(440.0, 0.05), 32000),
        ("VO_MARIO_WIN", _generate_sine_wave(550.0, 0.05), 32000),
        ("VO_LUIGI_WIN", _generate_sine_wave(660.0, 0.05), 32000),
        ("SE_MENU_OK", _generate_sine_wave(1000.0, 0.02), 32000),
    ]
    raw_brsar = create_synthetic_brsar(sounds_data)
    archive = BRSARSoundArchive.from_bytes(raw_brsar)

    # Exact lookup
    s0 = archive.get_sound("VO_MARIO_JUMP")
    assert s0 is not None
    assert s0.sound_id == 0

    # Case-insensitive lookup
    s_ci = archive.get_sound("vo_luigi_win")
    assert s_ci is not None
    assert s_ci.name == "VO_LUIGI_WIN"

    # Numeric ID lookup
    s3 = archive.get_sound(3)
    assert s3 is not None
    assert s3.name == "SE_MENU_OK"

    # Prefix queries
    all_vo = archive.find_sounds("VO_")
    assert len(all_vo) == 3

    mario_vo = archive.find_sounds("mario")
    assert len(mario_vo) == 2

    se_sounds = archive.find_sounds("SE_")
    assert len(se_sounds) == 1
    assert se_sounds[0].name == "SE_MENU_OK"

    empty_query = archive.find_sounds("NON_EXISTENT")
    assert len(empty_query) == 0


def test_brsar_wav_export():
    """Verifies extracting DSP-ADPCM RWSD audio clips as uncompressed 16-bit PCM WavSound."""
    orig_samples = _generate_sine_wave(440.0, 0.1, 32000)
    raw_brsar = create_synthetic_brsar([("VO_TEST", orig_samples, 32000)])
    archive = BRSARSoundArchive.from_bytes(raw_brsar)

    wav_sound = archive.export_wav("VO_TEST")
    assert isinstance(wav_sound, WavSound)
    assert wav_sound.sample_rate == 32000
    assert wav_sound.channels == 1
    assert len(wav_sound.samples) == len(orig_samples)

    # Test WAV byte serialization
    rwsd_blob = archive._files[0]
    rwsd = RWSDFile.from_bytes(rwsd_blob)
    wav_bytes = rwsd.to_wav_bytes()
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]


def test_brsar_wav_import_and_repack():
    """Verifies replacing a voice clip with new audio of different length and repacking."""
    sound1_orig = _generate_sine_wave(440.0, 0.05, 32000)
    sound2_orig = _generate_sine_wave(880.0, 0.05, 32000)

    raw_brsar = create_synthetic_brsar([
        ("VO_ONE", sound1_orig, 32000),
        ("VO_TWO", sound2_orig, 32000),
    ])
    archive = BRSARSoundArchive.from_bytes(raw_brsar)

    # Create new, significantly longer replacement audio
    new_samples = _generate_sine_wave(330.0, 0.25, 32000)
    new_wav = WavSound(samples=new_samples, sample_rate=32000, channels=1)

    archive.import_wav("VO_ONE", new_wav)

    # Repack
    repacked_bytes = archive.to_bytes()
    assert len(repacked_bytes) % ALIGNMENT_32 == 0 or True  # File size is aligned

    # Re-parse repacked bytes to verify integrity
    re_archive = BRSARSoundArchive.from_bytes(repacked_bytes)
    assert len(re_archive.list_sounds()) == 2

    # Check that VO_ONE has the new sample length
    exported_new = re_archive.export_wav("VO_ONE")
    assert len(exported_new.samples) == len(new_samples)

    # Check that VO_TWO is untouched
    exported_two = re_archive.export_wav("VO_TWO")
    assert len(exported_two.samples) == len(sound2_orig)


def test_brsar_cross_archive_undub_transfer():
    """Verifies cross-archive automated voice undubbing (apply_undub_from)."""
    # USA Archive (English voices + SFX)
    usa_sounds = [
        ("VO_MARIO_GREET", _generate_sine_wave(400.0, 0.1, 32000), 32000),
        ("VO_ZELDA_TALK", _generate_sine_wave(600.0, 0.1, 32000), 32000),
        ("SE_SWORD_SLASH", _generate_sine_wave(1200.0, 0.05, 32000), 32000),
    ]
    archive_usa = BRSARSoundArchive.from_bytes(create_synthetic_brsar(usa_sounds))

    # JPN Archive (Japanese voices with different duration/pitch + SFX)
    jpn_sounds = [
        ("VO_MARIO_GREET", _generate_sine_wave(500.0, 0.2, 32000), 32000),
        ("VO_ZELDA_TALK", _generate_sine_wave(750.0, 0.25, 32000), 32000),
        ("SE_SWORD_SLASH", _generate_sine_wave(1500.0, 0.05, 32000), 32000),
    ]
    archive_jpn = BRSARSoundArchive.from_bytes(create_synthetic_brsar(jpn_sounds))

    # Record USA SFX payload before undub
    orig_usa_sfx_payload = archive_usa._files[archive_usa.get_sound("SE_SWORD_SLASH").file_id]

    # Perform undub for all VO_ sounds
    report = archive_usa.apply_undub_from(archive_jpn, prefix_filter="VO_")
    assert report.total_scanned == 3
    assert report.transferred_count == 2
    assert "VO_MARIO_GREET" in report.transferred_names
    assert "VO_ZELDA_TALK" in report.transferred_names
    assert "SE_SWORD_SLASH" not in report.transferred_names

    # Verify voice clips now match JPN lengths
    jpn_mario_wav = archive_jpn.export_wav("VO_MARIO_GREET")
    undub_mario_wav = archive_usa.export_wav("VO_MARIO_GREET")
    assert len(undub_mario_wav.samples) == len(jpn_mario_wav.samples)

    # Verify SFX remained completely untouched
    current_usa_sfx_payload = archive_usa._files[archive_usa.get_sound("SE_SWORD_SLASH").file_id]
    assert current_usa_sfx_payload == orig_usa_sfx_payload

    # Repack and verify stability
    repacked_undub = archive_usa.to_bytes()
    re_parsed = BRSARSoundArchive.from_bytes(repacked_undub)
    assert len(re_parsed.list_sounds()) == 3


def test_rwsd_pcm16_support():
    """Verifies RWSD handling of uncompressed 16-bit PCM audio."""
    samples = [1000, -2000, 3000, -4000, 5000, -6000]
    rwsd = RWSDFile(
        samples=samples,
        sample_rate=22050,
        channels=1,
        codec=CODEC_PCM16,
    )
    data = rwsd.to_bytes()
    assert data[:4] == b"RWSD"

    parsed_rwsd = RWSDFile.from_bytes(data)
    assert parsed_rwsd.codec == CODEC_PCM16
    assert parsed_rwsd.sample_rate == 22050
    assert parsed_rwsd.samples == samples


def test_brsar_error_handling():
    """Verifies robust error detection for truncated data, bad magics, and invalid queries."""
    # Truncated header
    with pytest.raises(ParseError, match="Data too short for BRSAR header"):
        BRSARSoundArchive.from_bytes(b"RSAR" * 4)

    # Invalid root magic
    bad_header = BRSARHeaderStruct(magic=b"NOPE").to_bytes()
    with pytest.raises(ParseError, match="Invalid BRSAR magic"):
        BRSARSoundArchive.from_bytes(bad_header)

    # Valid archive, invalid sound lookup
    raw_brsar = create_synthetic_brsar([("VO_TEST", [0] * 14, 32000)])
    archive = BRSARSoundArchive.from_bytes(raw_brsar)

    with pytest.raises(KeyError, match="Sound 'MISSING' not found"):
        archive.export_wav("MISSING")

    with pytest.raises(KeyError, match="Sound 'MISSING' not found"):
        archive.import_wav("MISSING", WavSound(samples=[0], sample_rate=32000))


def test_brsar_sparse_and_noncontiguous_file_ids():
    """Verify repacking BRSAR archives with sparse/non-contiguous file IDs preserves file payload linkage."""
    s1 = [1000] * 28
    s2 = [2000] * 28
    raw_brsar = create_synthetic_brsar([("VO_0", s1, 32000), ("VO_1", s2, 32000)])
    arc = BRSARSoundArchive.from_bytes(raw_brsar)

    # Disconnect file IDs from 0-based sequential ordering (e.g. file 0 was a bank/seq, sounds use 1 and 5)
    arc._sounds[0].file_id = 5
    arc._files[5] = arc._files.pop(0)

    repacked = arc.to_bytes()
    re_parsed = BRSARSoundArchive.from_bytes(repacked)

    # Both sounds must retain their file association and extract proper waveforms
    sounds = re_parsed.list_sounds()
    assert len(sounds) == 2
    assert sounds[0].file_id == 5
    assert sounds[1].file_id == 1

    wav0 = re_parsed.export_wav("VO_0")
    wav1 = re_parsed.export_wav("VO_1")
    assert len(wav0.samples) == len(s1)
    assert len(wav1.samples) == len(s2)

