"""
test_nds_swar.py - Unit tests for Nintendo DS Nitro Sound Wave Archive (SWAR)
and Sound Wave (SWAV) sample parser, extractor, and rebuilder in MioROM.
Zero external dependencies.
"""

import math
import os
import struct
import pytest

from miorom.audio.adpcm import ADPCMCodec
from miorom.platforms.nds.swar import SWARArchive, SWAVEntry


def _generate_test_wav(freq: float = 440.0, rate: int = 22050, duration: float = 0.2) -> bytes:
    """Generates a synthetic 16-bit PCM WAV container."""
    total_samples = int(rate * duration)
    samples = [int(8000 * math.sin(2.0 * math.pi * freq * i / rate)) for i in range(total_samples)]
    return ADPCMCodec.build_wav(samples, sample_rate=rate, channels=1)


def test_mock_swav_adpcm_and_pcm16_roundtrip():
    """Test SWAVEntry encoding from WAV and decoding back to WAV for PCM16 and IMA-ADPCM."""
    wav_bytes = _generate_test_wav(freq=500.0, rate=16000, duration=0.1)
    orig_info = ADPCMCodec.read_wav(wav_bytes)

    # 1. PCM16 SWAV
    swav_pcm16 = SWAVEntry.from_wav(wav_bytes, wave_type=1, loop_flag=0, index=0)
    assert swav_pcm16.wave_type == 1
    assert swav_pcm16.sample_rate == 16000
    pcm16_wav = swav_pcm16.to_wav()
    pcm16_info = ADPCMCodec.read_wav(pcm16_wav)
    assert pcm16_info["samples"] == orig_info["samples"]

    # 2. IMA-ADPCM SWAV
    swav_adpcm = SWAVEntry.from_wav(wav_bytes, wave_type=2, loop_flag=1, loop_start_samples=100, index=1)
    assert swav_adpcm.wave_type == 2
    assert swav_adpcm.loop_flag == 1
    adpcm_wav = swav_adpcm.to_wav()
    adpcm_info = ADPCMCodec.read_wav(adpcm_wav)
    assert len(adpcm_info["samples"]) > 0


def test_real_rf1_swar_dataset(tmp_path):
    """Test parsing, extraction, and rebuilding on actual Rune Factory 1 SWAR archives."""
    swar_dir = "/mnt/sdcard/MiokoTech/Rune Factory 1 nds/workspace/audio/swar"
    if not os.path.isdir(swar_dir):
        pytest.skip("Rune Factory 1 SWAR files not found in workspace/audio/swar.")

    main_arc_p = os.path.join(swar_dir, "Bgm_MAIN_ARC.swar")
    se_arc_p = os.path.join(swar_dir, "WAVE_SE.swar")

    if not os.path.isfile(main_arc_p) or not os.path.isfile(se_arc_p):
        pytest.skip("SWAR archives not present.")

    # 1. Test WAVE_SE.swar (16 samples)
    se_swar = SWARArchive.from_file(se_arc_p)
    assert se_swar.num_swav == 16
    assert len(se_swar.samples) == 16

    # Extract WAVE_SE samples to temporary directory
    extract_dir = str(tmp_path / "wave_se")
    manifest = se_swar.extract_all(extract_dir)
    assert manifest["extracted_count"] == 16
    assert os.path.isfile(os.path.join(extract_dir, "000.wav"))
    assert os.path.isfile(os.path.join(extract_dir, "swar_manifest.json"))

    # Test rebuilding WAVE_SE container
    rebuilt_se_bytes = se_swar.to_bytes()
    re_se = SWARArchive(rebuilt_se_bytes)
    assert re_se.num_swav == 16
    assert len(re_se.samples) == 16

    # 2. Test Bgm_MAIN_ARC.swar (121 samples)
    bgm_swar = SWARArchive.from_file(main_arc_p)
    assert bgm_swar.num_swav == 121
    assert len(bgm_swar.samples) == 121

    # Verify first sample decoding
    sample0 = bgm_swar.samples[0]
    assert sample0 is not None
    s0_wav = sample0.to_wav()
    s0_info = ADPCMCodec.read_wav(s0_wav)
    assert s0_info["channels"] == 1
    assert len(s0_info["samples"]) > 0

    # Test rebuilding Bgm_MAIN_ARC container
    rebuilt_bgm_bytes = bgm_swar.to_bytes()
    re_bgm = SWARArchive(rebuilt_bgm_bytes)
    assert re_bgm.num_swav == 121
    assert len(re_bgm.samples) == 121
