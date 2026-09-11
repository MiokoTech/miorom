import pytest
import struct
from miorom.audio.spc import SpcFile, SpcHeader
from miorom.audio.brr import BRRCodec


def make_dummy_spc(
    song_title: str = "Chrono Trigger Theme",
    game_title: str = "Chrono Trigger",
    dumper_name: str = "Mioko",
    dir_page: int = 0x3C,
) -> bytes:
    buf = bytearray(0x10200)

    # Magic signature
    buf[0:33] = b"SNES-SPC700 Sound File Data v0.30"
    buf[0x21:0x23] = b"\x1A\x1A"
    buf[0x23] = 0x1A  # ID666 tag present
    buf[0x24] = 0x1E  # v0.30

    # Registers: PC=0x0800, A=1, X=2, Y=3, PSW=0, SP=0xFF
    struct.pack_into("<HBBBBB", buf, 0x25, 0x0800, 1, 2, 3, 0, 0xFF)

    # ID666 text tags
    buf[0x2E:0x4E] = song_title.encode("ascii")[:32].ljust(32, b"\x00")
    buf[0x4E:0x6E] = game_title.encode("ascii")[:32].ljust(32, b"\x00")
    buf[0x6E:0x7E] = dumper_name.encode("ascii")[:16].ljust(16, b"\x00")
    buf[0x7E:0x9E] = b"SNES Audio Test".ljust(32, b"\x00")
    buf[0x9E:0xA9] = b"2026-09-10\x00"
    buf[0xA9:0xAC] = b"120"  # 120 seconds duration
    buf[0xB1:0xD1] = b"Yasunori Mitsuda".ljust(32, b"\x00")

    # DSP register 0x3D = DIR page
    dsp_offset = 0x10100
    buf[dsp_offset + 0x3D] = dir_page

    # Place sample directory at DIR page (0x3C00 in RAM -> file offset 0x100 + 0x3C00 = 0x3D00)
    ram_offset = 0x100
    dir_file_offset = ram_offset + (dir_page << 8)

    sample0_ram_addr = 0x4000
    sample0_loop_addr = 0x4000
    struct.pack_into("<HH", buf, dir_file_offset, sample0_ram_addr, sample0_loop_addr)

    # Encode a minimal BRR block at sample0 (0x4000 in RAM -> file offset 0x100 + 0x4000 = 0x4100)
    sample_file_offset = ram_offset + sample0_ram_addr
    # Header byte: shift=0, filter=0, loop=0, end=1 (0x01)
    # Followed by 8 data bytes
    buf[sample_file_offset:sample_file_offset + 9] = b"\x01\x00\x00\x00\x00\x00\x00\x00\x00"

    return bytes(buf)


def test_spc_parse_and_header():
    raw = make_dummy_spc()
    spc = SpcFile.from_bytes(raw)

    assert spc.header.song_title == "Chrono Trigger Theme"
    assert spc.header.game_title == "Chrono Trigger"
    assert spc.header.dumper_name == "Mioko"
    assert spc.header.artist == "Yasunori Mitsuda"
    assert spc.header.duration_seconds == 120
    assert spc.header.pc == 0x0800
    assert spc.header.a == 1
    assert spc.header.x == 2
    assert spc.header.y == 3
    assert spc.header.sp == 0xFF


def test_spc_roundtrip_serialization():
    raw = make_dummy_spc()
    spc = SpcFile.from_bytes(raw)

    serialized = spc.to_bytes()
    reloaded = SpcFile.from_bytes(serialized)

    assert reloaded.header.song_title == spc.header.song_title
    assert reloaded.header.game_title == spc.header.game_title
    assert reloaded.header.pc == spc.header.pc
    assert reloaded.ram == spc.ram
    assert reloaded.dsp_regs == spc.dsp_regs


def test_spc_sample_extraction():
    raw = make_dummy_spc(dir_page=0x3C)
    spc = SpcFile.from_bytes(raw)

    assert spc.get_dsp_dir_address() == 0x3C00
    samples = spc.list_samples()
    assert len(samples) >= 1
    idx, start, loop = samples[0]
    assert idx == 0
    assert start == 0x4000
    assert loop == 0x4000

    # Extract raw BRR bytes
    brr = spc.extract_brr_sample(start)
    assert len(brr) == 9
    assert brr[0] == 0x01  # end flag

    all_samples = spc.extract_all_samples()
    assert 0 in all_samples
    assert len(all_samples[0]) == 9

    # Dump to WAV
    wav_dict = spc.dump_samples_to_wav(sample_rate=32000)
    assert 0 in wav_dict
    assert wav_dict[0].startswith(b"RIFF")


def test_spc_ram_read_write():
    raw = make_dummy_spc()
    spc = SpcFile.from_bytes(raw)

    spc.write_ram(0x1000, b"TEST_AUDIO_CODE")
    assert spc.read_ram(0x1000, 15) == b"TEST_AUDIO_CODE"

    with pytest.raises(IndexError):
        spc.read_ram(0xFFFF, 10)


def test_spc_invalid_inputs():
    with pytest.raises(ValueError):
        SpcFile.from_bytes(b"\x00" * 100)

    with pytest.raises(ValueError):
        SpcFile.from_bytes(b"INVALID-SIGNATURE" + b"\x00" * 0x10200)
