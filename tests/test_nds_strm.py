"""
test_nds_strm.py - Unit tests for Nintendo DS Nitro Stream (STRM) audio parser,
decoder, and encoder in MioROM.
Zero external dependencies.
"""

import math
import os
import struct
import pytest

from miorom.audio.adpcm import ADPCMCodec
from miorom.platforms.nds.strm import STRMFile


def _generate_sine_wav(
    freq: float = 440.0,
    sample_rate: int = 16364,
    duration_secs: float = 0.5,
    channels: int = 1,
    amplitude: int = 8000,
) -> bytes:
    """Generates a synthetic 16-bit PCM WAV container."""
    total_samples = int(sample_rate * duration_secs)
    samples = []
    for i in range(total_samples):
        val = int(amplitude * math.sin(2.0 * math.pi * freq * i / sample_rate))
        if channels == 1:
            samples.append(val)
        else:
            samples.append(val)
            # Second channel slightly lower pitch
            val_r = int(amplitude * math.sin(2.0 * math.pi * (freq * 0.75) * i / sample_rate))
            samples.append(val_r)

    return ADPCMCodec.build_wav(samples, sample_rate=sample_rate, channels=channels)


def test_mock_strm_pcm16_roundtrip():
    """Test that PCM16 STRM encoding and decoding produces 100% bit-exact samples."""
    wav_bytes = _generate_sine_wav(freq=440.0, sample_rate=22050, duration_secs=0.2, channels=1)
    orig_info = ADPCMCodec.read_wav(wav_bytes)

    # Encode to PCM16 STRM
    strm = STRMFile.from_wav(wav_bytes, wave_type=1, block_size=512)
    assert strm.header.wave_type == 1
    assert strm.header.channels == 1
    assert strm.header.sample_rate == 22050
    assert strm.header.num_samples == len(orig_info["samples"])

    # Decode back to WAV
    rebuilt_wav = strm.to_wav()
    rebuilt_info = ADPCMCodec.read_wav(rebuilt_wav)
    assert rebuilt_info["channels"] == 1
    assert rebuilt_info["sample_rate"] == 22050
    assert rebuilt_info["samples"] == orig_info["samples"]


def test_mock_strm_adpcm_mono_roundtrip():
    """Test that IMA-ADPCM STRM mono encoding and decoding retains high signal fidelity."""
    wav_bytes = _generate_sine_wav(freq=440.0, sample_rate=16364, duration_secs=0.3, channels=1)
    orig_info = ADPCMCodec.read_wav(wav_bytes)

    # Encode to IMA-ADPCM STRM
    strm = STRMFile.from_wav(wav_bytes, wave_type=2, block_size=512)
    assert strm.header.wave_type == 2
    assert strm.header.channels == 1
    assert strm.header.sample_rate == 16364
    assert strm.header.num_samples == len(orig_info["samples"])

    # Verify serialization
    strm_bytes = strm.to_bytes()
    strm_reloaded = STRMFile(strm_bytes)
    assert strm_reloaded.header.num_samples == strm.header.num_samples

    # Decode to WAV
    rebuilt_wav = strm_reloaded.to_wav()
    rebuilt_info = ADPCMCodec.read_wav(rebuilt_wav)
    assert rebuilt_info["sample_rate"] == 16364
    assert len(rebuilt_info["samples"]) == len(orig_info["samples"])

    # Verify error is low (ADPCM lossy compression tolerance)
    diffs = [abs(o - r) for o, r in zip(orig_info["samples"], rebuilt_info["samples"])]
    avg_diff = sum(diffs) / len(diffs)
    assert avg_diff < 500  # High SNR for 16-bit dynamic range


def test_mock_strm_adpcm_stereo_roundtrip():
    """Test stereo IMA-ADPCM STRM encoding and decoding."""
    wav_bytes = _generate_sine_wav(freq=300.0, sample_rate=16364, duration_secs=0.2, channels=2)
    orig_info = ADPCMCodec.read_wav(wav_bytes)

    strm = STRMFile.from_wav(wav_bytes, wave_type=2, block_size=512)
    assert strm.header.channels == 2
    assert strm.header.wave_type == 2

    rebuilt_wav = strm.to_wav()
    rebuilt_info = ADPCMCodec.read_wav(rebuilt_wav)
    assert rebuilt_info["channels"] == 2
    assert len(rebuilt_info["samples"]) == len(orig_info["samples"])


def test_real_rf1_strm_dataset():
    """Test parsing, decoding to WAV, and re-encoding on actual Rune Factory 1 STRM assets."""
    strm_dir = "/mnt/sdcard/MiokoTech/Rune Factory 1 nds/workspace/audio/strm"
    if not os.path.isdir(strm_dir):
        pytest.skip("Rune Factory 1 STRM files not found in workspace/audio/strm.")

    test_files = ["STRM_FISH_HIT.strm", "STRM_BRUSH.strm"]
    for fname in test_files:
        fpath = os.path.join(strm_dir, fname)
        if not os.path.isfile(fpath):
            continue

        strm = STRMFile.from_file(fpath)
        assert strm.header.wave_type == 2  # All RF1 streams are IMA-ADPCM
        assert strm.header.channels == 1
        assert strm.header.sample_rate in (16364, 47605)
        assert strm.header.num_samples > 0

        # Decode to WAV
        wav_bytes = strm.to_wav()
        wav_info = ADPCMCodec.read_wav(wav_bytes)
        assert wav_info["sample_rate"] == strm.header.sample_rate
        assert wav_info["channels"] == 1
        assert len(wav_info["samples"]) == strm.header.num_samples

        # Re-encode from WAV to STRM
        re_strm = STRMFile.from_wav(wav_bytes, wave_type=2, block_size=strm.header.block_size)
        assert re_strm.header.num_samples == strm.header.num_samples
        assert re_strm.header.sample_rate == strm.header.sample_rate
        assert re_strm.header.channels == strm.header.channels
