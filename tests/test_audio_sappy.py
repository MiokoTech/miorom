import struct
import pytest
from miorom.audio.sappy import (
    SappyCodec,
    SappyScanner,
    SappySample,
    SappyInstrument,
    SappySongEntry,
    is_gba_rom_ptr,
    gba_ptr_to_offset,
    offset_to_gba_ptr,
)
from miorom.errors import ParseError


def test_gba_pointer_utilities():
    ptr = 0x08040000
    assert is_gba_rom_ptr(ptr, 0x100000) is True
    assert gba_ptr_to_offset(ptr) == 0x040000
    assert offset_to_gba_ptr(0x040000) == ptr

    # Out of ROM bounds
    assert is_gba_rom_ptr(0x02000000, 0x100000) is False  # EWRAM
    assert is_gba_rom_ptr(0x08200000, 0x100000) is False  # Exceeds ROM size


def test_sappy_sample_codec_and_wav_export():
    # Synthetic signed 8-bit waveform
    raw_pcm = bytes([0, 32, 64, 127, 64, 0, 224, 192, 128, 192, 224])
    encoded = SappyCodec.encode_sample(
        raw_pcm,
        sample_rate=18157,
        loop_start=4,
        loop_enabled=True,
    )
    assert len(encoded) == 16 + len(raw_pcm)

    sample = SappyCodec.parse_sample(encoded, 0)
    assert sample.sample_rate == 18157
    assert sample.loop_start == 4
    assert sample.loop_enabled is True
    assert sample.length == len(raw_pcm)
    assert sample.data == raw_pcm

    # Export to WAV
    wav_bytes = sample.to_wav()
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert wav_bytes[12:16] == b"fmt "
    rate = struct.unpack_from("<I", wav_bytes, 24)[0]
    assert rate == 18157
    data_marker = wav_bytes.find(b"data")
    assert data_marker != -1
    data_size = struct.unpack_from("<I", wav_bytes, data_marker + 4)[0]
    assert data_size == len(raw_pcm)


def test_sappy_scanner_song_and_voice_tables():
    rom = bytearray(0x40000)  # 256 KB synthetic ROM

    # Setup 1 sample at offset 0x1000 (GBA ptr 0x08001000)
    sample_off = 0x1000
    sample_ptr = offset_to_gba_ptr(sample_off)
    sample_pcm = bytes([10, 20, 30, 40, 50] * 10)
    sample_blob = SappyCodec.encode_sample(sample_pcm, sample_rate=13379)
    rom[sample_off : sample_off + len(sample_blob)] = sample_blob

    # Setup Voice Table at offset 0x2000 (GBA ptr 0x08002000)
    vt_off = 0x2000
    vt_ptr = offset_to_gba_ptr(vt_off)
    # Instrument 0: DirectSound sample pointing to sample_ptr
    struct.pack_into("BBBB", rom, vt_off, 0x00, 60, 0, 0)  # inst_type=0, root=60
    struct.pack_into("<I", rom, vt_off + 4, sample_ptr)
    struct.pack_into("BBBB", rom, vt_off + 8, 255, 0, 255, 0)  # ADSR

    # Instrument 1: Drum kit (type 0x40) pointing to sub-table
    struct.pack_into("BBBB", rom, vt_off + 12, 0x40, 60, 0, 0)
    struct.pack_into("<I", rom, vt_off + 16, vt_ptr)

    # Setup 8 Song Headers starting at 0x3000
    # Each song header: track_count (1B), 0, priority, reverb, voice_table_ptr (4B)
    song_table_off = 0x4000
    for i in range(8):
        sh_off = 0x3000 + i * 32
        sh_ptr = offset_to_gba_ptr(sh_off)
        rom[sh_off] = 2  # 2 tracks
        rom[sh_off + 1] = 0
        rom[sh_off + 2] = 0  # priority
        rom[sh_off + 3] = 0  # reverb
        struct.pack_into("<I", rom, sh_off + 4, vt_ptr)  # voice table

        # Add to Song Table at 0x4000
        st_entry_off = song_table_off + i * 8
        struct.pack_into("<IHH", rom, st_entry_off, sh_ptr, 0, 0)

    # Scan for song tables
    candidates = SappyScanner.scan_song_tables(bytes(rom), min_consecutive_songs=8)
    assert song_table_off in candidates

    # Parse song table
    songs = SappyScanner.parse_song_table(bytes(rom), song_table_off)
    assert len(songs) == 8
    assert songs[0].track_count == 2
    assert songs[0].voice_table_ptr == vt_ptr
    assert songs[0].voice_table_offset == vt_off

    # Parse voice table
    instruments = SappyScanner.parse_voice_table(bytes(rom), vt_off, count=2)
    assert len(instruments) == 2
    assert instruments[0].is_direct_sound is True
    assert instruments[0].sample is not None
    assert instruments[0].sample.length == len(sample_pcm)

    assert instruments[1].is_drum_kit is True
    assert instruments[1].sub_table_ptr == vt_ptr

    # Rip samples
    ripped = SappyScanner.rip_samples(bytes(rom), vt_off)
    assert 0 in ripped
    assert ripped[0].length == len(sample_pcm)
