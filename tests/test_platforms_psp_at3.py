"""
tests/test_platforms_psp_at3.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Sony PlayStation Portable (PSP) ATRAC3 and ATRAC3plus
audio container parser, metadata inspector, loop point editor, and PSPRom integration.
"""

import pytest

from miorom.errors import ParseError
from miorom.platforms.iso.builder import ISOBuilder
from miorom.platforms.psp import (
    AT3Audio,
    AT3Codec,
    PSPRom,
    create_synthetic_at3,
)
from miorom.platforms.psp.at3 import (
    ATRAC3_GUID,
    RIFF_MAGIC,
    WAVE_FORMAT_EXTENSIBLE,
    WAVE_MAGIC,
    RiffHeaderStruct,
    SmplChunkHeaderStruct,
    SmplLoopEntryStruct,
    WaveFormatExStruct,
)


def test_atrac3_synthetic_parsing():
    """Verify parsing of standard Sony ATRAC3 RIFF WAVE streams with loop points."""
    at3_bytes = create_synthetic_at3(
        codec=AT3Codec.ATRAC3,
        sample_rate=44100,
        channels=2,
        bitrate_kbps=132,
        num_frames=10,
        loop_start_sample=1024,
        loop_end_sample=9216,
    )

    audio = AT3Audio.from_bytes(at3_bytes)
    assert audio.codec == AT3Codec.ATRAC3
    assert audio.channels == 2
    assert audio.sample_rate == 44100
    assert audio.bitrate_kbps == 132
    assert audio.frame_size == 384
    assert audio.samples_per_frame == 1024
    assert audio.total_samples == 10240
    assert audio.duration_seconds == round(10240 / 44100, 4)

    # Loop inspection
    assert audio.is_looped is True
    assert audio.loop_point is not None
    assert audio.loop_point.start_sample == 1024
    assert audio.loop_point.end_sample == 9216
    assert audio.loop_point.start_seconds == round(1024 / 44100, 4)
    assert audio.loop_point.end_seconds == round(9216 / 44100, 4)

    # Payload
    assert len(audio.audio_data) == 10 * 384


def test_atrac3plus_synthetic_parsing():
    """Verify parsing of Sony ATRAC3plus extensible GUID audio streams."""
    plus_bytes = create_synthetic_at3(
        codec=AT3Codec.ATRAC3PLUS,
        sample_rate=48000,
        channels=2,
        bitrate_kbps=128,
        num_frames=6,
    )

    audio = AT3Audio.from_bytes(plus_bytes)
    assert audio.codec == AT3Codec.ATRAC3PLUS
    assert audio.channels == 2
    assert audio.sample_rate == 48000
    assert audio.frame_size == 512
    assert audio.samples_per_frame == 2048
    assert audio.total_samples == 6 * 2048
    assert audio.is_looped is False
    assert audio.loop_point is None


def test_at3_loop_modification():
    """Verify updating loop points on an existing looped AT3 file."""
    at3_bytes = create_synthetic_at3(
        codec=AT3Codec.ATRAC3,
        sample_rate=44100,
        num_frames=12,
        loop_start_sample=1024,
        loop_end_sample=8192,
    )
    audio = AT3Audio.from_bytes(at3_bytes)

    # Update loop points
    audio.set_loop(start_sample=2048, end_sample=10000)
    assert audio.loop_point is not None
    assert audio.loop_point.start_sample == 2048
    assert audio.loop_point.end_sample == 10000

    # Verify persistence after round-trip serialization
    reloaded = AT3Audio.from_bytes(audio.to_bytes())
    assert reloaded.is_looped is True
    assert reloaded.loop_point is not None
    assert reloaded.loop_point.start_sample == 2048
    assert reloaded.loop_point.end_sample == 10000


def test_at3_set_loop_on_unlooped():
    """Verify synthesizing and injecting a new smpl chunk on an unlooped audio file."""
    at3_bytes = create_synthetic_at3(
        codec=AT3Codec.ATRAC3,
        sample_rate=44100,
        num_frames=10,
        loop_start_sample=None,
        loop_end_sample=None,
    )
    audio = AT3Audio.from_bytes(at3_bytes)
    assert audio.is_looped is False

    audio.set_loop(start_sample=512, end_sample=4096)
    assert audio.is_looped is True
    assert audio.loop_point is not None
    assert audio.loop_point.start_sample == 512
    assert audio.loop_point.end_sample == 4096

    # Verify serialized binary integrity
    reloaded = AT3Audio.from_bytes(audio.to_bytes())
    assert reloaded.is_looped is True
    assert reloaded.loop_point is not None
    assert reloaded.loop_point.start_sample == 512
    assert reloaded.loop_point.end_sample == 4096


def test_at3_invalid_loop_range():
    """Verify validation error when loop end is less than or equal to start."""
    at3_bytes = create_synthetic_at3()
    audio = AT3Audio.from_bytes(at3_bytes)
    with pytest.raises(ValueError) as exc:
        audio.set_loop(start_sample=5000, end_sample=4000)
    assert "must be greater than" in str(exc.value)


def test_at3_remove_loop():
    """Verify stripping the smpl chunk converts audio into a one-shot track."""
    at3_bytes = create_synthetic_at3(
        loop_start_sample=1024,
        loop_end_sample=4096,
    )
    audio = AT3Audio.from_bytes(at3_bytes)
    assert audio.is_looped is True
    orig_size = len(audio.to_bytes())

    audio.remove_loop()
    assert audio.is_looped is False
    assert audio.loop_point is None

    new_bytes = audio.to_bytes()
    assert len(new_bytes) < orig_size

    reloaded = AT3Audio.from_bytes(new_bytes)
    assert reloaded.is_looped is False
    assert reloaded.loop_point is None


def test_at3_replace_data():
    """Verify replacing compressed audio frame payload and updating sample statistics."""
    at3_bytes = create_synthetic_at3(num_frames=4)
    audio = AT3Audio.from_bytes(at3_bytes)
    assert audio.total_samples == 4 * 1024

    new_payload = b"\x12\x34" * (8 * 384 // 2)  # 8 frames
    audio.replace_data(new_payload)

    assert audio.total_samples == 8 * 1024
    assert audio.audio_data == new_payload

    reloaded = AT3Audio.from_bytes(audio.to_bytes())
    assert reloaded.total_samples == 8 * 1024
    assert reloaded.audio_data == new_payload


def test_at3_invalid_riff():
    """Verify error on corrupted or non-RIFF audio containers."""
    with pytest.raises(ParseError) as exc:
        AT3Audio.from_bytes(b"NOT_A_RIFF_FILE" * 2)
    assert "Invalid RIFF header magic" in str(exc.value)

    with pytest.raises(ParseError) as exc2:
        AT3Audio.from_bytes(b"RIFF\x0c\x00\x00\x00AVI ")
    assert "Invalid RIFF form type" in str(exc2.value)


def test_at3_file_io(tmp_path):
    """Verify reading from and writing to filesystem."""
    at3_bytes = create_synthetic_at3(loop_start_sample=100, loop_end_sample=2000)
    audio = AT3Audio.from_bytes(at3_bytes)

    out_file = tmp_path / "bgm.at3"
    audio.save(out_file)
    assert out_file.exists()

    loaded = AT3Audio.from_file(out_file)
    assert loaded.codec == AT3Codec.ATRAC3
    assert loaded.is_looped is True
    assert loaded.loop_point is not None
    assert loaded.loop_point.start_sample == 100


def test_psprom_boot_audio_integration():
    """Verify reading, editing, and replacing SND0.AT3 in PSPRom."""
    at3_data = create_synthetic_at3(
        sample_rate=44100,
        num_frames=6,
        loop_start_sample=500,
        loop_end_sample=4000,
    )

    # Build ISO with custom SND0.AT3
    builder = ISOBuilder(volume_id="TEST_AT3_DISC")
    builder.add_file("PSP_GAME/PARAM.SFO", b"\x00PSF\x01\x01\x00\x00" + b"\x00" * 32)
    builder.add_file("PSP_GAME/SND0.AT3", at3_data)
    iso_bytes = builder.build()

    rom = PSPRom(iso_bytes)
    audio = rom.get_boot_audio_at3()
    assert audio is not None
    assert audio.codec == AT3Codec.ATRAC3
    assert audio.is_looped is True
    assert audio.loop_point is not None
    assert audio.loop_point.start_sample == 500

    # Modify audio loop point and save back to ROM
    audio.set_loop(1000, 5000)
    rom.set_boot_audio_at3(audio)

    # Reload ROM
    rom2 = PSPRom(rom.to_bytes())
    reloaded_audio = rom2.get_boot_audio_at3()
    assert reloaded_audio is not None
    assert reloaded_audio.loop_point is not None
    assert reloaded_audio.loop_point.start_sample == 1000
    assert reloaded_audio.loop_point.end_sample == 5000


def test_psprom_find_audio_streams():
    """Verify deep scanning and discovery of embedded AT3 streams in game disc files."""
    at3_bgm = create_synthetic_at3(codec=AT3Codec.ATRAC3, num_frames=4)
    at3_voice = create_synthetic_at3(codec=AT3Codec.ATRAC3PLUS, num_frames=4)

    # Embed both into a single dummy container
    container_bytes = b"HEADER_DUMMY" + at3_bgm + b"SEPARATOR_DUMMY" + at3_voice

    builder = ISOBuilder(volume_id="AUDIO_DISC")
    builder.add_file("PSP_GAME/PARAM.SFO", b"\x00PSF\x01\x01\x00\x00" + b"\x00" * 32)
    builder.add_file("PSP_GAME/USRDIR/SOUND_ARCHIVE.BIN", container_bytes)
    iso_bytes = builder.build()

    rom = PSPRom(iso_bytes)
    streams = rom.find_audio_streams()

    assert len(streams) == 2
    fpath1, off1, audio1 = streams[0]
    assert "SOUND_ARCHIVE.BIN" in fpath1
    assert audio1.codec == AT3Codec.ATRAC3

    fpath2, off2, audio2 = streams[1]
    assert "SOUND_ARCHIVE.BIN" in fpath2
    assert audio2.codec == AT3Codec.ATRAC3PLUS


def test_at3_raw_data_riff_sync():
    """Verify raw_data RIFF size stays synchronized across loop mutations and data replacement."""
    at3_bytes = create_synthetic_at3(num_frames=8)
    audio = AT3Audio.from_bytes(at3_bytes)
    assert audio.is_looped is False

    # 1. set_loop: inserts smpl chunk (68 bytes)
    audio.set_loop(1000, 5000)
    assert audio.is_looped is True
    # Crucial: instantiate directly from audio.raw_data without calling to_bytes()
    reloaded1 = AT3Audio(audio.raw_data)
    assert len(reloaded1.raw_data) == len(audio.raw_data)
    assert reloaded1.is_looped is True
    assert reloaded1.loop_point.start_sample == 1000
    assert reloaded1.loop_point.end_sample == 5000

    # 2. remove_loop: removes smpl chunk
    audio.remove_loop()
    assert audio.is_looped is False
    reloaded2 = AT3Audio(audio.raw_data)
    assert len(reloaded2.raw_data) == len(audio.raw_data)
    assert reloaded2.is_looped is False

    # 3. replace_data: changes payload length
    new_payload = b"\x55" * (12 * audio.frame_size)
    audio.replace_data(new_payload)
    reloaded3 = AT3Audio(audio.raw_data)
    assert len(reloaded3.raw_data) == len(audio.raw_data)
    assert reloaded3.audio_data == new_payload


def test_at3_set_loop_inactive_smpl():
    """Verify set_loop updates cSampleLoops to 1 when existing smpl has cSampleLoops == 0."""
    at3_bytes = create_synthetic_at3(num_frames=6)
    audio = AT3Audio.from_bytes(at3_bytes)

    # Manually inject smpl chunk with cSampleLoops = 0
    hdr = SmplChunkHeaderStruct()
    hdr.cSampleLoops = 0
    entry = SmplLoopEntryStruct()
    entry.dwStart = 100
    entry.dwEnd = 500
    smpl_payload = hdr.to_bytes(endian="<") + entry.to_bytes(endian="<")
    smpl_chunk = b"smpl" + len(smpl_payload).to_bytes(4, "little") + smpl_payload

    # Insert smpl before data
    data_pos = audio.raw_data.find(b"data")
    audio.raw_data[data_pos:data_pos] = smpl_chunk
    audio._parse_chunks()
    audio._parse_loop()
    assert audio.is_looped is False  # Because cSampleLoops is 0

    # Now call set_loop
    audio.set_loop(200, 800)
    assert audio.is_looped is True

    # Reload and verify loop was preserved
    reloaded = AT3Audio.from_bytes(audio.to_bytes())
    assert reloaded.is_looped is True
    assert reloaded.loop_point is not None
    assert reloaded.loop_point.start_sample == 200
    assert reloaded.loop_point.end_sample == 800


def test_at3_set_loop_validation():
    """Verify validation of bounds in set_loop."""
    at3_bytes = create_synthetic_at3(num_frames=4)
    audio = AT3Audio.from_bytes(at3_bytes)

    with pytest.raises(ValueError, match="non-negative"):
        audio.set_loop(-5, 1000)

    with pytest.raises(ValueError, match="must be greater than"):
        audio.set_loop(1000, 1000)

    with pytest.raises(ValueError, match="cannot exceed total_samples"):
        audio.set_loop(100, audio.total_samples + 500)


def test_at3_extensible_atrac3_guid():
    """Verify WAVE_FORMAT_EXTENSIBLE with ATRAC3_GUID is parsed as ATRAC3."""
    import io

    # Create format chunk with WAVE_FORMAT_EXTENSIBLE + ATRAC3_GUID
    wfmt = WaveFormatExStruct()
    wfmt.wFormatTag = WAVE_FORMAT_EXTENSIBLE
    wfmt.nChannels = 2
    wfmt.nSamplesPerSec = 44100
    wfmt.nAvgBytesPerSec = (132 * 1000) // 8
    wfmt.nBlockAlign = 384
    wfmt.wBitsPerSample = 0

    fmt_buf = io.BytesIO()
    fmt_buf.write(wfmt.to_bytes(endian="<"))
    fmt_buf.write((34).to_bytes(2, "little"))  # cbSize
    fmt_buf.write((0).to_bytes(2, "little"))
    fmt_buf.write((3).to_bytes(4, "little"))
    fmt_buf.write(ATRAC3_GUID)
    fmt_buf.write(b"\x00" * 12)
    fmt_payload = fmt_buf.getvalue()

    # Fact and data
    fact_payload = (4096).to_bytes(4, "little") + (1024).to_bytes(4, "little")
    data_payload = b"\x00" * (4 * 384)

    out = io.BytesIO()
    out.write(b"\x00" * 12)
    for cid, pay in [(b"fmt ", fmt_payload), (b"fact", fact_payload), (b"data", data_payload)]:
        out.write(cid + len(pay).to_bytes(4, "little") + pay)
    raw = bytearray(out.getvalue())
    hdr = RiffHeaderStruct()
    hdr.magic = RIFF_MAGIC
    hdr.file_size = len(raw) - 8
    hdr.form_type = WAVE_MAGIC
    raw[:12] = hdr.to_bytes(endian="<")

    audio = AT3Audio.from_bytes(bytes(raw))
    assert audio.codec == AT3Codec.ATRAC3
    assert audio.samples_per_frame == 1024


def test_at3_corrupted_chunk_size():
    """Verify ParseError is raised when chunk size exceeds container boundary."""
    at3_bytes = bytearray(create_synthetic_at3(num_frames=2))
    # Find 'data' chunk size and corrupt it to exceed EOF
    data_idx = at3_bytes.find(b"data")
    at3_bytes[data_idx + 4 : data_idx + 8] = (0x7FFFFFFF).to_bytes(4, "little")

    with pytest.raises(ParseError, match="exceeds container boundary"):
        AT3Audio.from_bytes(bytes(at3_bytes))

