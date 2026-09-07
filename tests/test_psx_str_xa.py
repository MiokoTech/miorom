import struct
from miorom.audio.xa import CdXaDecoder, cdxa_to_wav, decode_cdxa_sector
from miorom.platforms.psx import StrDemuxer


def test_cdxa_decode_and_wav():
    # Construct a dummy 2304-byte CD-XA audio sector
    # 18 sound groups of 128 bytes
    sec_data = bytearray(2304)
    for g in range(18):
        offset = g * 128
        # Header: filter 0, shift 0 for all 8 sound units
        sec_data[offset:offset + 16] = b"\x00" * 16
        # Fill samples with alternating nibbles 1 and -1 (0x1 and 0xF)
        sec_data[offset + 16:offset + 128] = b"\x1F" * (128 - 16)

    # Decode sector
    pcm = decode_cdxa_sector(bytes(sec_data), stereo=True, bits=4)
    assert len(pcm) > 0
    assert len(pcm) % 4 == 0  # 16-bit stereo = 4 bytes per sample pair

    # Check that sample values are within signed 16-bit range
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    for s in samples:
        assert -32768 <= s <= 32767

    # Export to WAV
    wav = cdxa_to_wav([bytes(sec_data)], sample_rate=37800, stereo=True)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"
    assert len(wav) == 44 + len(pcm)


def test_str_demuxer():
    # Build raw 2352-byte sectors:
    # Sector 0: Audio sector
    sec0 = bytearray(2352)
    sec0[:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
    sec0[0x10] = 1   # file
    sec0[0x11] = 2   # channel
    sec0[0x12] = 0x44  # submode (Audio)
    sec0[0x13] = 0x01  # coding (Stereo)
    sec0[0x18:0x18 + 2304] = b"\x00" * 2304

    # Sector 1: Video sector - Frame 0, Chunk 0 of 2
    sec1 = bytearray(2352)
    sec1[:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
    sec1[0x10] = 1
    sec1[0x11] = 0
    sec1[0x12] = 0x22  # submode (Video)
    # STR chunk header: magic=0x0160, chan=0x0100, chunk_idx=0, chunk_cnt=2, frame_idx=0, bytes_used=3000, w=320, h=240
    struct.pack_into("<HHHHIIHH", sec1, 0x18, 0x0160, 0x0100, 0, 2, 0, 3000, 320, 240)
    sec1[0x18 + 32:0x18 + 32 + 2016] = b"\xAA" * 2016

    # Sector 2: Video sector - Frame 0, Chunk 1 of 2
    sec2 = bytearray(2352)
    sec2[:12] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\x00"
    sec2[0x10] = 1
    sec2[0x11] = 0
    sec2[0x12] = 0x22  # submode (Video)
    struct.pack_into("<HHHHIIHH", sec2, 0x18, 0x0160, 0x0100, 1, 2, 0, 3000, 320, 240)
    sec2[0x18 + 32:0x18 + 32 + 2016] = b"\xBB" * 2016

    raw_str = bytes(sec0 + sec1 + sec2)

    demuxer = StrDemuxer(raw_str)
    assert len(demuxer.sectors) == 3
    assert demuxer.sector_size == 2352

    # Audio extraction
    audio_sec = demuxer.get_audio_sectors(channel=2)
    assert len(audio_sec) == 1
    wav_data = demuxer.demux_audio(channel=2)
    assert wav_data[:4] == b"RIFF"

    # Video extraction
    frames = demuxer.demux_video_frames()
    assert len(frames) == 1
    f0 = frames[0]
    assert f0.frame_index == 0
    assert f0.width == 320
    assert f0.height == 240
    assert f0.chunks_found == 2
    assert f0.chunks_total == 2
    assert f0.is_complete is True
    # Verify concatenated payload trimmed to bytes_used (3000)
    assert len(f0.bs_data) == 3000
    assert f0.bs_data[:2016] == b"\xAA" * 2016
    assert f0.bs_data[2016:3000] == b"\xBB" * (3000 - 2016)
