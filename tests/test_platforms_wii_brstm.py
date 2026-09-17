"""
tests/test_platforms_wii_brstm.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii & GameCube BRSTM Audio Stream Engine.
Tests cover:
- BRSTM header and HEAD/ADPC/DATA section binary parsing and serialization
- DSP-ADPCM single-channel encoding and decoding fidelity
- Synthetic stereo BRSTM creation, multi-channel interleaving, and roundtrip
- Loop point manipulation and duration calculations
- Bi-directional WAV bridge (WAV -> BRSTM -> WAV)
- File disk saving and summary diagnostics
"""

from __future__ import annotations

import math
import os
import tempfile

import pytest

from miorom.audio.dsp_adpcm import DSPADPCMCodec
from miorom.audio.wav_codec import WavCodec, WavSound
from miorom.platforms.wii import BRSTMChannelInfo, BRSTMFile
from miorom.platforms.wii.brstm import (
    RSTM_MAGIC,
    BRSTMHeaderStruct,
    BRSTMHeadPart1Struct,
    encode_dsp_adpcm_channel,
)


def _generate_sine_pcm(freq: float, duration_s: float, sample_rate: int = 44100, amplitude: float = 20000.0) -> list[int]:
    """Helper to synthesize a clean 16-bit signed PCM sine wave."""
    total_samples = int(duration_s * sample_rate)
    samples = []
    for i in range(total_samples):
        t = i / sample_rate
        val = int(amplitude * math.sin(2.0 * math.pi * freq * t))
        samples.append(max(-32768, min(32767, val)))
    return samples


def test_brstm_header_and_structs():
    """Verify BRSTM header and HEAD part 1 binary structures."""
    hdr = BRSTMHeaderStruct(
        magic=RSTM_MAGIC,
        bom=0xFEFF,
        version=0x0200,
        file_size=0x1000,
        header_size=0x40,
        section_count=2,
        head_offset=0x40,
        head_size=0x100,
        data_offset=0x140,
        data_size=0xEC0,
    )
    b_hdr = hdr.to_bytes()
    assert len(b_hdr) == 0x40
    assert b_hdr[:4] == b"RSTM"

    parsed = BRSTMHeaderStruct.from_bytes(b_hdr, offset=0)
    assert parsed.bom == 0xFEFF
    assert parsed.version == 0x0200
    assert parsed.file_size == 0x1000

    p1 = BRSTMHeadPart1Struct(
        codec=2,
        loop_flag=1,
        channels=2,
        sample_rate=32000,
        loop_start=16000,
        total_samples=64000,
    )
    b_p1 = p1.to_bytes()
    assert len(b_p1) == BRSTMHeadPart1Struct.sizeof()

    parsed_p1 = BRSTMHeadPart1Struct.from_bytes(b_p1, offset=0)
    assert parsed_p1.codec == 2
    assert parsed_p1.channels == 2
    assert parsed_p1.sample_rate == 32000
    assert parsed_p1.loop_start == 16000
    assert parsed_p1.total_samples == 64000


def test_dsp_adpcm_encoder_and_decoder_fidelity():
    """Verify encoding 16-bit PCM into DSP-ADPCM and decoding back with high SNR."""
    sine_samples = _generate_sine_pcm(440.0, 0.1, sample_rate=32000)  # 3200 samples
    adpcm_data, coefs, _, _ = encode_dsp_adpcm_channel(sine_samples)

    # 14 samples per 8-byte frame
    expected_frames = (len(sine_samples) + 13) // 14
    assert len(adpcm_data) == expected_frames * 8

    # Decode
    decoded = DSPADPCMCodec.decode(adpcm_data, coefs=coefs)
    assert len(decoded) >= len(sine_samples)

    # Calculate Signal-to-Noise Ratio (SNR)
    signal_power = sum(s * s for s in sine_samples)
    noise_power = sum((orig - dec) ** 2 for orig, dec in zip(sine_samples, decoded[:len(sine_samples)]))

    assert noise_power > 0
    snr = 10.0 * math.log10(signal_power / noise_power)
    # DSP-ADPCM 4-bit typical SNR for sine is > 20 dB
    assert snr > 15.0


def test_synthetic_stereo_brstm_roundtrip():
    """Verify creating a multi-channel interleaved BRSTM stream and roundtrip serialization."""
    sample_rate = 44100
    ch0_samples = _generate_sine_pcm(440.0, 0.4, sample_rate=sample_rate)   # 440 Hz Left
    ch1_samples = _generate_sine_pcm(880.0, 0.4, sample_rate=sample_rate)   # 880 Hz Right
    total_samples = len(ch0_samples)

    # Encode both channels
    adpcm_0, coefs_0, _, _ = encode_dsp_adpcm_channel(ch0_samples)
    adpcm_1, coefs_1, _, _ = encode_dsp_adpcm_channel(ch1_samples)

    info_0 = BRSTMChannelInfo(coefs=coefs_0)
    info_1 = BRSTMChannelInfo(coefs=coefs_1)

    brstm = BRSTMFile(
        sample_rate=sample_rate,
        channels=2,
        loop=True,
        loop_start=4410,  # 0.1s
        total_samples=total_samples,
        channel_info=[info_0, info_1],
        raw_channel_data=[adpcm_0, adpcm_1],
        block_size=0x2000,
    )

    assert pytest.approx(brstm.duration_seconds, rel=1e-3) == 0.4
    assert pytest.approx(brstm.loop_duration_seconds, rel=1e-3) == 0.3

    # Serialize to bytes
    raw_brstm = brstm.to_bytes()
    assert len(raw_brstm) > 0x100
    assert raw_brstm[:4] == b"RSTM"

    # Parse back
    loaded = BRSTMFile.from_bytes(raw_brstm)
    assert loaded.sample_rate == sample_rate
    assert loaded.channels == 2
    assert loaded.loop is True
    assert loaded.loop_start == 4410
    assert loaded.total_samples == total_samples
    assert len(loaded.channel_info) == 2

    # Verify decoded PCM
    pcm = loaded.decode_pcm()
    assert len(pcm) == total_samples * 2  # stereo interleaved


def test_loop_point_editing():
    """Verify updating loop points and boundary validation."""
    brstm = BRSTMFile(
        sample_rate=44100,
        channels=2,
        loop=False,
        loop_start=0,
        total_samples=88200,  # 2.0s
    )
    assert brstm.loop is False
    assert brstm.loop_duration_seconds == 0.0

    # Set valid loop at 1.0s (sample 44100)
    brstm.set_loop(loop_start=44100)
    assert brstm.loop is True
    assert brstm.loop_start == 44100
    assert pytest.approx(brstm.loop_duration_seconds, rel=1e-3) == 1.0

    # Invalid loop start out of bounds
    with pytest.raises(ValueError, match="Invalid loop_start"):
        brstm.set_loop(loop_start=100000)

    # Invalid total samples <= loop start
    with pytest.raises(ValueError, match="strictly greater"):
        brstm.set_loop(loop_start=20000, total_samples=10000)


def test_wav_conversion_bridge():
    """Verify bidirectional WAV -> BRSTM -> WAV conversion."""
    sample_rate = 32000
    left_samples = _generate_sine_pcm(330.0, 0.25, sample_rate=sample_rate)
    right_samples = _generate_sine_pcm(660.0, 0.25, sample_rate=sample_rate)
    total_samples = len(left_samples)

    # Create synthetic WAV
    interleaved_samples: list[int] = []
    for left, right in zip(left_samples, right_samples):
        interleaved_samples.extend([left, right])

    wav_in = WavSound(samples=interleaved_samples, channels=2, sample_rate=sample_rate, bits_per_sample=16)
    wav_bytes = WavCodec.encode(wav_in)

    # Encode to BRSTM
    brstm = BRSTMFile.from_wav(wav_bytes, loop=True, loop_start=3200)
    assert brstm.channels == 2
    assert brstm.sample_rate == sample_rate
    assert brstm.total_samples == total_samples
    assert brstm.loop is True
    assert brstm.loop_start == 3200

    # Export back to WAV
    wav_out_bytes = brstm.to_wav()
    wav_out = WavCodec.decode(wav_out_bytes)

    assert wav_out.channels == 2
    assert wav_out.sample_rate == sample_rate
    assert wav_out.num_frames == total_samples
    assert len(wav_out.samples) == total_samples * 2


def test_file_disk_save_and_summary():
    """Verify saving BRSTM to disk, loading from file, and summary diagnostics."""
    samples = _generate_sine_pcm(440.0, 0.2, sample_rate=32000)
    wav_sound = WavSound(samples=samples, channels=1, sample_rate=32000, bits_per_sample=16)
    wav_bytes = WavCodec.encode(wav_sound)

    brstm = BRSTMFile.from_wav(wav_bytes, loop=True, loop_start=1000)
    summary = brstm.summary()

    assert "BRSTM Audio Stream [Mono]" in summary
    assert "Sample Rate: 32000 Hz" in summary
    assert "Looping: True" in summary

    with tempfile.TemporaryDirectory() as tmpdir:
        brstm_path = os.path.join(tmpdir, "test.brstm")
        brstm.save(brstm_path)
        assert os.path.exists(brstm_path)
        assert os.path.getsize(brstm_path) > 0

        loaded = BRSTMFile.from_file(brstm_path)
        assert loaded.channels == 1
        assert loaded.sample_rate == 32000
        assert loaded.loop_start == 1000


def test_brstm_head_part1_specification_and_absolute_audio_offset():
    """Verify HEAD Part 1 adheres to 0x34-byte standard with absolute audio_data_offset."""
    # 1. Structural size verification
    assert BRSTMHeadPart1Struct.sizeof() == 0x34

    samples = _generate_sine_pcm(500.0, 0.1, sample_rate=32000)
    wav_sound = WavSound(samples=samples, channels=1, sample_rate=32000, bits_per_sample=16)
    brstm = BRSTMFile.from_wav(wav_sound.to_bytes(), loop=False)

    data = brstm.to_bytes()

    # Verify RSTM header offsets
    head_offset = int.from_bytes(data[0x10:0x14], "big")
    data_offset = int.from_bytes(data[0x20:0x24], "big")
    expected_audio_start = data_offset + 0x20

    # Read HEAD part 1 offsets
    p1_rel = int.from_bytes(data[head_offset + 8 : head_offset + 12], "big")
    p1_abs = head_offset + 8 + p1_rel
    p2_rel = int.from_bytes(data[head_offset + 12 : head_offset + 16], "big")

    # Part 2 should start after 0x34 bytes aligned to 4 bytes: 0x14 + 0x34 = 0x48
    assert p2_rel == 0x48

    p1 = BRSTMHeadPart1Struct.from_bytes(data, offset=p1_abs)
    # audio_data_offset must be the absolute file offset
    assert p1.audio_data_offset == expected_audio_start
    assert p1.final_block_padded_size > 0
    assert p1.final_block_padded_size % 0x20 == 0

    # 2. Verify decoding with absolute offset
    decoded_file = BRSTMFile.from_bytes(data)
    assert decoded_file.channels == 1
    assert decoded_file.total_samples == len(samples)
    pcm = decoded_file.decode_pcm()
    assert len(pcm) == len(samples)

