import os
import struct
import pytest
from miorom.platforms.cdrom import (
    CueSheet,
    CueTrack,
    CueBinDisc,
    msf_to_lba,
    lba_to_msf,
    parse_msf,
    format_msf,
    calculate_cdrom_edc,
)


def test_msf_lba_conversion():
    assert msf_to_lba(0, 2, 0) == 150
    assert msf_to_lba(1, 0, 0) == 4500
    assert lba_to_msf(150) == (0, 2, 0)
    assert parse_msf("01:20:15") == (1 * 60 + 20) * 75 + 15
    assert format_msf(150) == "00:02:00"


def test_cuesheet_parse_and_serialize():
    cue_text = """
    FILE "Castlevania.bin" BINARY
      TRACK 01 MODE2/2352
        INDEX 01 00:00:00
      TRACK 02 AUDIO
        PREGAP 00:02:00
        INDEX 01 15:30:00
    """
    cue = CueSheet.from_string(cue_text)
    assert len(cue.tracks) == 2
    assert cue.tracks[0].number == 1
    assert cue.tracks[0].track_type == "MODE2/2352"
    assert cue.tracks[0].file_name == "Castlevania.bin"
    assert cue.tracks[0].indexes[1] == 0

    assert cue.tracks[1].number == 2
    assert cue.tracks[1].track_type == "AUDIO"
    assert cue.tracks[1].pregap == 150
    assert cue.tracks[1].indexes[1] == msf_to_lba(15, 30, 0)

    serialized = cue.to_string()
    assert 'FILE "Castlevania.bin" BINARY' in serialized
    assert "TRACK 01 MODE2/2352" in serialized
    assert "TRACK 02 AUDIO" in serialized


def test_cdrom_edc_calculation():
    # Verify non-trivial byte stream calculation
    data = b"MioROM CD-ROM EDC Test Stream 12345"
    edc1 = calculate_cdrom_edc(data)
    edc2 = calculate_cdrom_edc(data)
    assert edc1 == edc2
    assert edc1 != 0


def test_cue_bin_disc_single_bin(tmp_path):
    # Create synthetic single-BIN CD image:
    # 2 sectors of MODE1/2352 (track 1) = 4704 bytes
    # 2 sectors of AUDIO (track 2) = 4704 bytes
    # Total BIN size = 9408 bytes
    bin_data = bytearray(9408)

    # Track 1, Sector 0 (LBA 0):
    bin_data[0:12] = b"\x00" + b"\xFF" * 10 + b"\x00"
    bin_data[12:16] = bytes([0x00, 0x02, 0x00, 0x01])  # 00:02:00, Mode 1
    bin_data[16:16 + 11] = b"HELLO_USER1"

    # Track 1, Sector 1 (LBA 1):
    off1 = 2352
    bin_data[off1:off1 + 12] = b"\x00" + b"\xFF" * 10 + b"\x00"
    bin_data[off1 + 12:off1 + 16] = bytes([0x00, 0x02, 0x01, 0x01])  # 00:02:01, Mode 1
    bin_data[off1 + 16:off1 + 16 + 11] = b"HELLO_USER2"

    # Track 2: 2 sectors of audio (4704 bytes of 16-bit PCM)
    audio_offset = 2352 * 2
    for i in range(2352):
        # Sine-wave like sample bytes
        bin_data[audio_offset + i * 2] = i & 0xFF
        bin_data[audio_offset + i * 2 + 1] = (i >> 8) & 0x7F

    cue_text = """
    FILE "game.bin" BINARY
      TRACK 01 MODE1/2352
        INDEX 01 00:00:00
      TRACK 02 AUDIO
        INDEX 01 00:00:02
    """
    cue = CueSheet.from_string(cue_text)
    disc = CueBinDisc.from_tracks(cue, {"game.bin": bytes(bin_data)})

    assert disc.track_count == 2
    t1 = disc.get_track(1)
    t2 = disc.get_track(2)
    assert t1.is_data_track
    assert t2.is_audio_track

    # Read sector 0 stripped: should be 2048 bytes starting with "HELLO_USER1"
    user_sec0 = disc.read_sector(1, 0, raw=False)
    assert len(user_sec0) == 2048
    assert user_sec0[:11] == b"HELLO_USER1"

    # Extract stripped data track: should be 4096 bytes
    stripped_t1 = disc.extract_track_data(1, raw=False)
    assert len(stripped_t1) == 4096
    assert stripped_t1[:11] == b"HELLO_USER1"
    assert stripped_t1[2048:2048 + 11] == b"HELLO_USER2"

    # Test replacing track 1 data with auto-sector packaging & EDC
    new_user_data = b"PATCHED_DATA_TRACK_PAYLOAD" + b"\x00" * (4096 - 26)
    disc.replace_track_data(1, new_user_data, is_raw=False)

    # Verify sector header & sync were rebuilt
    rebuilt_sec0 = disc.read_sector(1, 0, raw=True)
    assert rebuilt_sec0[:12] == b"\x00" + b"\xFF" * 10 + b"\x00"
    assert rebuilt_sec0[16:16 + 26] == b"PATCHED_DATA_TRACK_PAYLOAD"


def test_cd_da_wav_export_import(tmp_path):
    # 1 sector of CD-DA audio = 2352 bytes (588 stereo 16-bit samples)
    pcm = bytes([(i % 256) for i in range(2352)])
    cue_text = """
    FILE "audio.bin" BINARY
      TRACK 01 AUDIO
        INDEX 01 00:00:00
    """
    cue = CueSheet.from_string(cue_text)
    disc = CueBinDisc.from_tracks(cue, {"audio.bin": pcm})

    wav_path = str(tmp_path / "track01.wav")
    wav_bytes = disc.export_audio_track_wav(1, out_path=wav_path)

    assert os.path.exists(wav_path)
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert b"fmt " in wav_bytes
    assert b"data" in wav_bytes

    # Now modify audio and import it back
    modified_pcm = bytes([((i + 50) % 256) for i in range(2352)])
    # Build modified wav
    disc.bin_buffers["audio.bin"] = bytearray(modified_pcm)
    mod_wav_bytes = disc.export_audio_track_wav(1)

    # Re-import into disc
    disc.import_audio_track_wav(1, mod_wav_bytes)
    assert disc.extract_track_data(1, raw=True) == modified_pcm


def test_disc_load_and_save(tmp_path):
    cue_file = tmp_path / "disc.cue"
    bin1_file = tmp_path / "track1.bin"
    bin2_file = tmp_path / "track2.bin"

    bin1_file.write_bytes(b"\x00" * 2048)
    bin2_file.write_bytes(b"\x11" * 2352)

    cue_content = f"""
    FILE "{bin1_file.name}" BINARY
      TRACK 01 MODE1/2048
        INDEX 01 00:00:00
    FILE "{bin2_file.name}" BINARY
      TRACK 02 AUDIO
        INDEX 01 00:00:00
    """
    cue_file.write_text(cue_content)

    disc = CueBinDisc.load(str(cue_file))
    assert disc.track_count == 2

    # Save to a new folder
    out_dir = tmp_path / "exported"
    out_cue = str(out_dir / "disc.cue")
    disc.save(out_cue)

    assert os.path.exists(out_cue)
    assert os.path.exists(out_dir / bin1_file.name)
    assert os.path.exists(out_dir / bin2_file.name)


def test_disc_to_iso_bridge():
    # Build 17 sectors of 2048 bytes for MODE1/2048 to contain a valid ISO9660 PVD
    iso_raw = bytearray(18 * 2048)
    pvd_offset = 16 * 2048
    iso_raw[pvd_offset:pvd_offset + 6] = b"\x01CD001"
    iso_raw[pvd_offset + 40:pvd_offset + 72] = b"TEST_DISC_IMAGE                 "
    # Root dir entry: LBA 17, size 2048
    root_rec = pvd_offset + 156
    iso_raw[root_rec] = 34  # record length
    struct.pack_into("<I", iso_raw, root_rec + 2, 17)
    struct.pack_into("<I", iso_raw, root_rec + 10, 2048)

    cue_text = """
    FILE "game.iso" BINARY
      TRACK 01 MODE1/2048
        INDEX 01 00:00:00
    """
    cue = CueSheet.from_string(cue_text)
    disc = CueBinDisc.from_tracks(cue, {"game.iso": bytes(iso_raw)})

    iso_obj = disc.to_iso(1)
    assert iso_obj.volume_id == "TEST_DISC_IMAGE"


def test_replace_track_data_mode1_edc():
    """Verify Mode 1 replacement calculates Yellow Book standard EDC including SYNC_PATTERN."""
    cue_text = """
    FILE "game.bin" BINARY
      TRACK 01 MODE1/2352
        INDEX 01 00:00:00
    """
    cue = CueSheet.from_string(cue_text)
    disc = CueBinDisc.from_tracks(cue, {"game.bin": bytes(2352)})

    new_data = b"MODE1_PAYLOAD_TEST_DATA_" * 85 + b"12345678"  # exactly 2048 bytes
    assert len(new_data) == 2048
    disc.replace_track_data(1, new_data, is_raw=False)

    raw_sec = disc.bin_buffers["game.bin"][:2352]
    # Check sync pattern
    assert raw_sec[:12] == b"\x00" + b"\xFF" * 10 + b"\x00"
    # Check mode byte = 1
    assert raw_sec[15] == 0x01
    # Check user data at offset 16
    assert raw_sec[16:2064] == new_data

    # Check EDC checksum matches Yellow Book specification over sec[:2064]
    written_edc = struct.unpack("<I", raw_sec[2064:2068])[0]
    expected_edc = calculate_cdrom_edc(raw_sec[:2064])
    assert written_edc == expected_edc

    # Verify round-trip extraction
    extracted = disc.extract_track_data(1, raw=False)
    assert extracted == new_data


def test_replace_track_data_mode2_form1_and_roundtrip():
    """Verify Mode 2 Form 1 replacement writes subheaders, data at offset 24, and correct EDC."""
    cue_text = """
    FILE "psx.bin" BINARY
      TRACK 01 MODE2/2352
        INDEX 01 00:00:00
    """
    cue = CueSheet.from_string(cue_text)
    disc = CueBinDisc.from_tracks(cue, {"psx.bin": bytes(2352)})

    new_data = b"PSX_MODE2_USER_DATA_0123456789" * 68 + b"12345678"  # 2048 bytes
    assert len(new_data) == 2048
    disc.replace_track_data(1, new_data, is_raw=False)

    raw_sec = disc.bin_buffers["psx.bin"][:2352]
    # Check sync pattern
    assert raw_sec[:12] == b"\x00" + b"\xFF" * 10 + b"\x00"
    # Check mode byte = 2
    assert raw_sec[15] == 0x02
    # Check subheader at offset 16
    assert raw_sec[16:24] == b"\x00\x00\x08\x00\x00\x00\x08\x00"
    # Check user data at offset 24 (no 8-byte shift!)
    assert raw_sec[24:2072] == new_data

    # Check EDC checksum matches Mode 2 Form 1 specification over sec[16:2072]
    written_edc = struct.unpack("<I", raw_sec[2072:2076])[0]
    expected_edc = calculate_cdrom_edc(raw_sec[16:2072])
    assert written_edc == expected_edc

    # Verify round-trip extraction extracts the exact user data without shifting
    extracted = disc.extract_track_data(1, raw=False)
    assert extracted == new_data


def test_replace_track_data_multi_track_single_bin_delta():
    """Verify expanding track 1 in a single-BIN disc shifts subsequent track indexes correctly."""
    cue_text = """
    FILE "cd.bin" BINARY
      TRACK 01 MODE1/2352
        INDEX 01 00:00:00
      TRACK 02 AUDIO
        INDEX 01 00:00:01
    """
    cue = CueSheet.from_string(cue_text)
    audio_pcm = b"AUDIO_DATA_TRACK_2" * 130 + b"\x00" * (2352 - (len(b"AUDIO_DATA_TRACK_2" * 130)))
    bin_buf = bytearray(2352 + 2352)
    bin_buf[2352:] = audio_pcm

    disc = CueBinDisc.from_tracks(cue, {"cd.bin": bytes(bin_buf)})
    assert disc.get_track(2).indexes[1] == 1

    # Replace track 1 with 2 sectors of data (expanding by 1 sector)
    expanded_data = b"EXPANDED_TRACK1_SECTOR_" * (2048 * 2 // 23)
    expanded_data = expanded_data[:4096]
    disc.replace_track_data(1, expanded_data, is_raw=False)

    # Track 2's index in the single BIN must now be shifted from 1 to 2
    assert disc.get_track(2).indexes[1] == 2
    assert disc.get_track(1).sector_count == 2
    assert disc.get_track(2).sector_count == 1

    # Extract audio track and ensure data was not corrupted or clipped
    extracted_audio = disc.extract_track_data(2, raw=True)
    assert extracted_audio == audio_pcm

