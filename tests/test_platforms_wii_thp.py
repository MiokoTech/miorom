"""
tests/test_platforms_wii_thp.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit test suite for Nintendo GameCube & Wii THP Video Cutscene Engine.
Tests low-level binary structures, Motion JPEG frame demux/mux, continuous DSP-ADPCM
audio extraction/dubbing, frame replacement (hardsubbing), and error detection.
"""

import math
from typing import List

import pytest

from miorom.audio.wav_codec import WavSound
from miorom.errors import ParseError
from miorom.platforms.wii.thp import (
    THPFrame,
    THPHeaderStruct,
    THPMovie,
    create_synthetic_thp,
)


def _make_dummy_jpeg(color_seed: int = 1) -> bytes:
    """Helper to create a minimal valid JPEG bitstream stub starting with 0xFF 0xD8 and ending with 0xFF 0xD9."""
    header = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    payload = bytes([color_seed % 256] * 32)
    footer = b"\xff\xd9"
    return header + payload + footer


def _generate_sine_wave(frequency: float, duration_seconds: float, sample_rate: int = 32000) -> List[int]:
    """Helper to generate a simple sine wave as 16-bit signed PCM samples."""
    num_samples = int(duration_seconds * sample_rate)
    samples = []
    for i in range(num_samples):
        val = int(16000 * math.sin(2 * math.pi * frequency * i / sample_rate))
        samples.append(val)
    return samples


def test_thp_synthetic_creation_and_parse():
    """Verifies creating a synthetic THP movie and parsing headers and component metadata."""
    jpegs = [_make_dummy_jpeg(i) for i in range(5)]
    audio_samples = _generate_sine_wave(440.0, 5 / 30.0, 32000)

    raw_thp = create_synthetic_thp(
        width=640,
        height=480,
        fps=30.0,
        frames_jpegs=jpegs,
        audio_samples=audio_samples,
        sample_rate=32000,
    )
    assert raw_thp.startswith(b"THP\x00")

    movie = THPMovie.from_bytes(raw_thp)
    assert movie.width == 640
    assert movie.height == 480
    assert abs(movie.fps - 30.0) < 0.01
    assert movie.num_frames == 5
    assert movie.has_audio is True
    assert movie.audio_sample_rate == 32000
    assert movie.audio_channels == 1
    assert abs(movie.duration_seconds - (5 / 30.0)) < 0.01
    assert "THP Movie: 640x480" in movie.summary()


def test_thp_video_demux_and_frame_export(tmp_path):
    """Verifies demuxing video frames and exporting them to individual image files."""
    jpegs = [_make_dummy_jpeg(i + 10) for i in range(4)]
    raw_thp = create_synthetic_thp(
        width=320,
        height=240,
        fps=29.97,
        frames_jpegs=jpegs,
    )
    movie = THPMovie.from_bytes(raw_thp)
    assert movie.num_frames == 4

    # Frame retrieval
    f1 = movie.get_frame(1)
    assert isinstance(f1, THPFrame)
    assert f1.index == 1
    assert f1.get_image_bytes().startswith(b"\xff\xd8")
    assert f1.get_image_bytes().endswith(b"\xff\xd9")

    # Export frames to disk
    out_dir = tmp_path / "frames"
    exported = movie.export_frames(out_dir, prefix="cutscene_")
    assert len(exported) == 4
    for p in exported:
        with open(p, "rb") as f:
            data = f.read()
            assert data.startswith(b"\xff\xd8")
            assert data.endswith(b"\xff\xd9")


def test_thp_audio_demux_to_wav():
    """Verifies continuous DSP-ADPCM audio extraction across frames into a WavSound."""
    sample_rate = 32000
    fps = 30.0
    duration = 0.2  # 6 frames
    orig_samples = _generate_sine_wave(500.0, duration, sample_rate)
    jpegs = [_make_dummy_jpeg(i) for i in range(6)]

    raw_thp = create_synthetic_thp(
        width=640,
        height=480,
        fps=fps,
        frames_jpegs=jpegs,
        audio_samples=orig_samples,
        sample_rate=sample_rate,
    )
    movie = THPMovie.from_bytes(raw_thp)
    wav_sound = movie.export_audio_wav()

    assert isinstance(wav_sound, WavSound)
    assert wav_sound.sample_rate == sample_rate
    assert wav_sound.channels == 1
    # Sample count is within 1 frame buffer tolerance
    assert abs(len(wav_sound.samples) - len(orig_samples)) < (sample_rate / fps + 14)


def test_thp_audio_dubbing_replacement():
    """Verifies replacing cutscene audio with new dubbed audio and repacking without drift."""
    sample_rate = 32000
    fps = 30.0
    orig_audio = _generate_sine_wave(300.0, 0.2, sample_rate)
    jpegs = [_make_dummy_jpeg(i) for i in range(6)]

    movie = THPMovie.from_bytes(create_synthetic_thp(640, 480, fps, jpegs, orig_audio))

    # New dubbing audio with distinct frequency and samples
    new_audio_samples = _generate_sine_wave(800.0, 0.2, sample_rate)
    new_wav = WavSound(samples=new_audio_samples, sample_rate=sample_rate, channels=1)

    movie.set_audio_wav(new_wav)

    # Repack
    repacked = movie.to_bytes()
    re_movie = THPMovie.from_bytes(repacked)

    re_wav = re_movie.export_audio_wav()
    assert re_wav.sample_rate == sample_rate
    assert abs(len(re_wav.samples) - len(new_audio_samples)) < (sample_rate / fps + 14)


def test_thp_frame_replacement_and_hardsub():
    """Verifies replacing a specific frame image (burning a subtitle) and verifying movie rebuild."""
    jpegs = [_make_dummy_jpeg(i) for i in range(3)]
    movie = THPMovie.from_bytes(create_synthetic_thp(640, 480, 30.0, jpegs))

    subtitle_jpeg = _make_dummy_jpeg(99)
    movie.replace_frame(1, subtitle_jpeg)

    repacked = movie.to_bytes()
    re_movie = THPMovie.from_bytes(repacked)

    assert re_movie.get_frame(1).image_data == subtitle_jpeg
    assert re_movie.get_frame(0).image_data == jpegs[0]
    assert re_movie.get_frame(2).image_data == jpegs[2]


def test_thp_video_only_movie():
    """Verifies handling and repacking of silent video-only THP movies."""
    jpegs = [_make_dummy_jpeg(i) for i in range(4)]
    raw_thp = create_synthetic_thp(640, 480, 24.0, jpegs, audio_samples=None)

    movie = THPMovie.from_bytes(raw_thp)
    assert movie.has_audio is False

    repacked = movie.to_bytes()
    re_movie = THPMovie.from_bytes(repacked)
    assert re_movie.has_audio is False
    assert re_movie.num_frames == 4

    with pytest.raises(ValueError, match="THP movie does not have an audio track"):
        re_movie.export_audio_wav()


def test_thp_error_handling():
    """Verifies robust error handling for bad magics, truncated data, and out-of-bounds frame access."""
    # Truncated
    with pytest.raises(ParseError, match="Data too short for THP header"):
        THPMovie.from_bytes(b"THP\x00" * 2)

    # Bad magic
    bad_header = THPHeaderStruct(magic=b"BAD!").to_bytes()
    with pytest.raises(ParseError, match="Invalid THP magic"):
        THPMovie.from_bytes(bad_header)

    # Valid movie, out-of-bounds frame
    movie = THPMovie.from_bytes(create_synthetic_thp(640, 480, 30.0, [_make_dummy_jpeg(1)]))
    with pytest.raises(IndexError, match="out of range"):
        movie.get_frame(99)

    # Invalid JPEG for frame replacement
    with pytest.raises(ParseError, match="Image data does not appear to be a valid JPEG bitstream"):
        movie.replace_frame(0, b"NOT_A_JPEG")


def test_thp_stereo_audio_demux_and_dubbing():
    """Verifies standard Nintendo GameCube/Wii stereo THP audio demuxing, 80-byte header, and dubbing."""
    sample_rate = 32000
    fps = 30.0
    duration = 0.2  # 6 frames
    total_samples = int(duration * sample_rate)

    stereo_samples: List[int] = []
    for i in range(total_samples):
        # Left channel: 440Hz sine; Right channel: 880Hz sine
        s_l = int(14000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        s_r = int(14000 * math.sin(2 * math.pi * 880 * i / sample_rate))
        stereo_samples.extend([s_l, s_r])

    jpegs = [_make_dummy_jpeg(i) for i in range(6)]

    # Create synthetic stereo THP
    raw_stereo_thp = create_synthetic_thp(
        width=640,
        height=480,
        fps=fps,
        frames_jpegs=jpegs,
        audio_samples=stereo_samples,
        sample_rate=sample_rate,
        channels=2,
    )

    movie = THPMovie.from_bytes(raw_stereo_thp)
    assert movie.has_audio is True
    assert movie.audio_channels == 2
    assert movie.audio_sample_rate == sample_rate

    # Audio slice in frame 0 should use standard 80-byte stereo header (0x50)
    assert len(movie.frames[0].audio_data) >= 80

    # Demux to stereo WAV
    wav_stereo = movie.export_audio_wav()
    assert isinstance(wav_stereo, WavSound)
    assert wav_stereo.channels == 2
    assert wav_stereo.sample_rate == sample_rate

    # Left and Right channels must be distinct (not identical/mono)
    left_ch = wav_stereo.samples[0::2]
    right_ch = wav_stereo.samples[1::2]
    assert left_ch != right_ch

    # Test stereo dubbing replacement
    new_stereo_samples: List[int] = []
    for i in range(total_samples):
        new_l = int(10000 * math.sin(2 * math.pi * 220 * i / sample_rate))
        new_r = int(10000 * math.sin(2 * math.pi * 660 * i / sample_rate))
        new_stereo_samples.extend([new_l, new_r])

    dub_wav = WavSound(samples=new_stereo_samples, sample_rate=sample_rate, channels=2)
    movie.set_audio_wav(dub_wav)
    assert movie.audio_channels == 2

    # Repack and verify roundtrip
    repacked = movie.to_bytes()
    re_movie = THPMovie.from_bytes(repacked)
    assert re_movie.audio_channels == 2
    re_wav = re_movie.export_audio_wav()
    assert re_wav.channels == 2
    assert abs(len(re_wav.samples) - len(new_stereo_samples)) < (sample_rate / fps * 2 + 28)


def test_thp_max_buffer_size_specification_compliance():
    """Verifies max_buffer_size in root header includes the 16-byte frame slice header."""
    jpegs = [_make_dummy_jpeg(i) for i in range(3)]
    audio_samples = _generate_sine_wave(440.0, 0.1, 32000)

    raw_thp = create_synthetic_thp(
        width=640,
        height=480,
        fps=30.0,
        frames_jpegs=jpegs,
        audio_samples=audio_samples,
        sample_rate=32000,
        channels=1,
    )
    hdr = THPHeaderStruct.from_bytes(raw_thp, offset=0)
    movie = THPMovie.from_bytes(raw_thp)

    expected_max_buf = max(16 + len(f.image_data) + len(f.audio_data) for f in movie.frames)
    assert hdr.max_buffer_size == expected_max_buf
    assert hdr.max_buffer_size >= hdr.first_frame_size

