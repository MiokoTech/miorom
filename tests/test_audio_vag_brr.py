import math
import struct
import pytest

from miorom.audio.vag import VAGHeader, VAGCodec, VAGFile
from miorom.audio.brr import BRRCodec
from miorom.audio.dsp_adpcm import DSPADPCMCodec, DEFAULT_DSP_COEFFS
from miorom.errors import ParseError


def generate_sine_wave(num_samples: int, freq: float = 440.0, sample_rate: int = 44100, amp: int = 15000):
    return [
        int(amp * math.sin(2.0 * math.pi * freq * i / sample_rate))
        for i in range(num_samples)
    ]


def test_vag_header_roundtrip():
    header = VAGHeader(
        magic=b"VAGp",
        version=3,
        interleave=0,
        data_size=64,
        sample_rate=44100,
        name="TEST_SOUND",
    )
    raw = header.to_bytes()
    assert len(raw) == 48
    parsed = VAGHeader.from_bytes(raw)
    assert parsed.magic == b"VAGp"
    assert parsed.version == 3
    assert parsed.sample_rate == 44100
    assert parsed.name == "TEST_SOUND"


def test_vag_header_invalid():
    with pytest.raises(ParseError):
        VAGHeader.from_bytes(b"SHORT")
    with pytest.raises(ParseError):
        VAGHeader.from_bytes(b"NOPE" + b"\x00" * 44)


def test_vag_encode_decode_sine():
    # 56 samples = 2 blocks of 28 samples
    orig_samples = generate_sine_wave(56, freq=1000.0, sample_rate=44100, amp=12000)
    vag = VAGFile.from_pcm(orig_samples, sample_rate=44100, name="SINE")

    assert len(vag.audio_data) >= 32  # at least 2 data blocks + 1 termination block
    assert len(vag.audio_data) % 16 == 0

    # Test decode
    decoded = vag.decode()
    assert len(decoded) >= 56

    # Verify reconstruction fidelity (MSE should be low for SPU-ADPCM)
    for orig, rec in zip(orig_samples, decoded[:56]):
        assert abs(orig - rec) < 3000  # Quantization error tolerance

    # Test WAV conversion
    wav_bytes = vag.to_wav()
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes
    assert b"fmt " in wav_bytes
    assert b"data" in wav_bytes


def test_vag_file_bytes_roundtrip():
    samples = generate_sine_wave(28, freq=800.0, sample_rate=22050, amp=8000)
    vag1 = VAGFile.from_pcm(samples, sample_rate=22050, name="VOICE01")
    file_bytes = vag1.to_bytes()

    vag2 = VAGFile.from_bytes(file_bytes)
    assert vag2.header.sample_rate == 22050
    assert vag2.header.name == "VOICE01"
    assert vag2.decode() == vag1.decode()


def test_brr_codec_encode_decode():
    # 32 samples = 2 BRR blocks of 16 samples
    orig_samples = generate_sine_wave(32, freq=500.0, sample_rate=32000, amp=10000)
    brr_data = BRRCodec.encode(orig_samples)

    assert len(brr_data) == 18  # 2 blocks * 9 bytes
    # Second block should have END flag set (bit 0 = 1)
    assert (brr_data[9] & 0x01) == 1

    decoded = BRRCodec.decode(brr_data)
    assert len(decoded) == 32

    # Verify reconstruction
    for orig, rec in zip(orig_samples, decoded):
        assert abs(orig - rec) < 3000

    # Test WAV generation
    wav_bytes = BRRCodec.to_wav(brr_data, sample_rate=32000)
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes


def test_dsp_adpcm_decode_and_wav():
    # Test 8-byte DSP frame decode
    frame = b"\x00\x12\x34\x56\x78\x9A\xBC\xDE"
    samples = DSPADPCMCodec.decode(frame)
    assert len(samples) == 14

    wav_bytes = DSPADPCMCodec.to_wav(frame, sample_rate=32000)
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes
