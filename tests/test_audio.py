import pytest
from miorom.audio.adpcm import ADPCMCodec
from miorom.audio.sdat import SDATContainer


def test_adpcm_decoding_and_wav_builder():
    raw_adpcm = bytes([0x12, 0x34, 0x56, 0x78] * 100) # 400 bytes = 800 samples
    samples = ADPCMCodec.decode_ima(raw_adpcm)
    assert len(samples) == 800
    assert all(-32768 <= s <= 32767 for s in samples)

    wav = ADPCMCodec.build_wav(samples, sample_rate=16000, channels=1)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert b"data" in wav


def test_sdat_container_read_and_replace():
    # Construct minimal SDAT container
    # Header: 64 bytes
    header = bytearray(64)
    header[:4] = b"SDAT"

    fat_off = 64
    file_off = 96

    # FAT: 1 file entry (rel_offset = 0x20 = 32, size = 12 = 0x0C), padded to 32 bytes
    fat_data = bytearray(b"FAT \x20\x00\x00\x00\x01\x00\x00\x00\x20\x00\x00\x00\x0C\x00\x00\x00").ljust(32, b"\x00")
    # FILE: 12 bytes header + 20 bytes padding to 32 bytes + payload (12 bytes) = 44 bytes (0x2C)
    file_data = bytearray(b"FILE\x2C\x00\x00\x00\x01\x00\x00\x00") + (b"\x00" * 20) + b"HELLO SOUND!"

    import struct
    struct.pack_into("<II", header, 0x20, fat_off, len(fat_data))
    struct.pack_into("<II", header, 0x28, file_off, len(file_data))
    struct.pack_into("<I", header, 8, 64 + len(fat_data) + len(file_data))

    sdat_bytes = header + fat_data + file_data
    sdat = SDATContainer(bytes(sdat_bytes))

    assert len(sdat.entries) == 1
    assert sdat.get_file(0) == b"HELLO SOUND!"

    # Replace file
    sdat.replace_file(0, b"NEW AUDIO DATA!!")
    rebuilt = sdat.to_bytes()

    sdat_reloaded = SDATContainer(rebuilt)
    assert sdat_reloaded.get_file(0) == b"NEW AUDIO DATA!!"
