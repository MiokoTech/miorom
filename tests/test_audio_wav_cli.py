import math
import os
import tempfile

import pytest

from miorom.audio.brr import BRRCodec
from miorom.audio.spc import SpcFile, SpcHeader
from miorom.audio.vag import VAGFile
from miorom.audio.wav_codec import WavCodec
from miorom.cli.main import main
from miorom.core import schema
from miorom.errors import ParseError


def generate_sine(num_samples: int, freq: float = 440.0, rate: int = 44100, amp: int = 16000) -> list[int]:
    return [int(amp * math.sin(2.0 * math.pi * freq * i / rate)) for i in range(num_samples)]


def test_wav_codec_16bit_mono_roundtrip():
    samples = generate_sine(100, freq=440.0, rate=44100)
    wav_bytes = WavCodec.encode(samples, sample_rate=44100, channels=1, bits_per_sample=16)

    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes
    assert b"fmt " in wav_bytes
    assert b"data" in wav_bytes

    sound = WavCodec.decode(wav_bytes)
    assert sound.sample_rate == 44100
    assert sound.channels == 1
    assert sound.bits_per_sample == 16
    assert sound.num_frames == 100
    assert sound.samples == samples
    assert sound.get_channel(0) == samples
    assert round(sound.duration_seconds, 4) == round(100 / 44100, 4)


def test_wav_codec_stereo_and_to_mono():
    left = [1000, 2000, 3000, 4000]
    right = [-1000, -2000, -3000, -4000]
    interleaved = []
    for l_val, r_val in zip(left, right):
        interleaved.extend([l_val, r_val])

    wav_bytes = WavCodec.encode(interleaved, sample_rate=22050, channels=2, bits_per_sample=16)
    sound = WavCodec.decode(wav_bytes)

    assert sound.channels == 2
    assert sound.num_frames == 4
    assert sound.get_channel(0) == left
    assert sound.get_channel(1) == right

    with pytest.raises(IndexError):
        sound.get_channel(2)

    mono = sound.to_mono()
    assert mono.channels == 1
    assert mono.num_frames == 4
    assert mono.samples == [0, 0, 0, 0]


def test_wav_codec_8bit_roundtrip():
    samples = [0, 8000, -8000, 16000, -16000]
    wav_bytes = WavCodec.encode(samples, sample_rate=11025, channels=1, bits_per_sample=8)
    sound = WavCodec.decode(wav_bytes)

    assert sound.sample_rate == 11025
    assert sound.channels == 1
    assert sound.num_frames == len(samples)
    # 8-bit has quantization delta (~256 per step)
    for orig, rec in zip(samples, sound.samples):
        assert abs(orig - rec) <= 300


def test_wav_codec_float_and_24bit_decode():
    # Build 32-bit float WAV manually
    f_samples = [0.0, 0.5, -0.5, 1.0, -1.0]
    pcm_raw = bytearray()
    for f in f_samples:
        pcm_raw.extend(schema.pack("<f", f))

    header = bytearray(b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00")
    # format 3 (IEEE float), 1 channel, 48000 rate, 192000 byte_rate, 4 align, 32 bits
    header.extend(schema.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32))
    header.extend(b"data")
    header.extend(schema.pack("<I", len(pcm_raw)))
    schema.pack_into("<I", header, 4, len(header) - 8 + len(pcm_raw))

    wav_data = bytes(header + pcm_raw)
    sound = WavCodec.decode(wav_data)
    assert sound.sample_rate == 48000
    assert sound.channels == 1
    assert len(sound.samples) == 5
    assert sound.samples[0] == 0
    assert abs(sound.samples[1] - 16383) <= 2
    assert abs(sound.samples[2] - (-16383)) <= 2

    # Build 24-bit PCM WAV
    pcm_24 = bytearray()
    val_24 = 0x200000  # 24-bit positive number
    pcm_24.extend([val_24 & 0xFF, (val_24 >> 8) & 0xFF, (val_24 >> 16) & 0xFF])
    val_neg = -0x200000
    val_neg_u = val_neg & 0xFFFFFF
    pcm_24.extend([val_neg_u & 0xFF, (val_neg_u >> 8) & 0xFF, (val_neg_u >> 16) & 0xFF])

    h24 = bytearray(b"RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00")
    h24.extend(schema.pack("<HHIIHH", 1, 1, 44100, 44100 * 3, 3, 24))
    h24.extend(b"data")
    h24.extend(schema.pack("<I", len(pcm_24)))
    schema.pack_into("<I", h24, 4, len(h24) - 8 + len(pcm_24))

    s24 = WavCodec.decode(bytes(h24 + pcm_24))
    assert len(s24.samples) == 2
    assert s24.samples[0] == 0x2000
    assert s24.samples[1] == -0x2000


def test_wav_codec_inspect_and_errors():
    with pytest.raises(ParseError):
        WavCodec.decode(b"SHORT")
    with pytest.raises(ParseError):
        WavCodec.decode(b"RIFF" + b"\x00" * 40)
    with pytest.raises(ValueError):
        WavCodec.encode([1, 2, 3], bits_per_sample=12)

    samples = generate_sine(50)
    wav_bytes = WavCodec.encode(samples, sample_rate=22050, channels=1)
    info = WavCodec.inspect(wav_bytes)
    assert info["sample_rate"] == 22050
    assert info["channels"] == 1
    assert info["num_samples"] == 50


def test_vag_and_brr_from_wav():
    samples = generate_sine(56, freq=440.0, rate=44100)
    wav_bytes = WavCodec.encode(samples, sample_rate=44100, channels=1)

    # VAG from WAV
    vag = VAGFile.from_wav(wav_bytes, name="VAGTEST")
    assert vag.header.sample_rate == 44100
    assert vag.header.name == "VAGTEST"
    assert len(vag.decode()) >= 56

    # BRR from WAV
    brr_bytes = BRRCodec.from_wav(wav_bytes)
    assert len(brr_bytes) >= 18
    assert (brr_bytes[-9] & 0x01) == 1  # end flag


def test_cli_audio_convert_and_info(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_in = os.path.join(tmpdir, "test.wav")
        vag_out = os.path.join(tmpdir, "test.vag")
        brr_out = os.path.join(tmpdir, "test.brr")
        wav_rebuilt = os.path.join(tmpdir, "rebuilt.wav")

        samples = generate_sine(56, freq=440.0, rate=32000)
        WavCodec.encode_file(wav_in, samples, sample_rate=32000, channels=1)

        # 1. Info on WAV
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "info", wav_in, "--json"])
        main()

        # 2. Convert WAV -> VAG
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "convert", wav_in, "-o", vag_out])
        main()
        assert os.path.exists(vag_out)
        assert os.path.getsize(vag_out) > 48

        # 3. Info on VAG
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "info", vag_out])
        main()

        # 4. Convert VAG -> WAV
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "convert", vag_out, "-o", wav_rebuilt])
        main()
        assert os.path.exists(wav_rebuilt)
        rebuilt_sound = WavCodec.decode_file(wav_rebuilt)
        assert rebuilt_sound.sample_rate == 32000

        # 5. Convert WAV -> BRR
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "convert", wav_in, "-o", brr_out])
        main()
        assert os.path.exists(brr_out)

        # 6. Info on BRR
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "info", brr_out])
        main()


def test_cli_audio_extract_spc_and_sdat(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create minimal valid SPC
        spc_path = os.path.join(tmpdir, "test.spc")
        samples_pcm = generate_sine(32, freq=600.0, rate=32000)
        brr_sample = BRRCodec.encode(samples_pcm)

        ram = bytearray(65536)
        # Put BRR at RAM 0x1000
        ram[0x1000 : 0x1000 + len(brr_sample)] = brr_sample
        # Sample directory at 0x0200: entry 0 = start 0x1000, loop 0x1000
        ram[0x0200:0x0204] = b"\x00\x10\x00\x10"

        dsp_regs = bytearray(128)
        dsp_regs[0x3D] = 0x02  # DIR page = 2 (0x0200)

        header = SpcHeader(
            song_title="Test Theme",
            game_title="Super Mio",
            dumper_name="MioDev",
            artist="Composer",
            duration_seconds=120,
        )
        spc = SpcFile(header=header, ram=bytes(ram), dsp_regs=bytes(dsp_regs))
        with open(spc_path, "wb") as f:
            f.write(spc.to_bytes())

        # Test SPC info
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "info", spc_path])
        main()

        # Test SPC extract
        out_spc_dir = os.path.join(tmpdir, "spc_wavs")
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "extract", spc_path, "-o", out_spc_dir])
        main()
        assert os.path.exists(os.path.join(out_spc_dir, "sample_000.wav"))

        # Create minimal SDAT
        sdat_path = os.path.join(tmpdir, "test.sdat")
        sdat_header = bytearray(64)
        sdat_header[:4] = b"SDAT"
        fat_off = 64
        file_off = 96
        fat_data = bytearray(b"FAT \x20\x00\x00\x00\x01\x00\x00\x00\x20\x00\x00\x00\x08\x00\x00\x00").ljust(32, b"\x00")
        file_data = bytearray(b"FILE\x28\x00\x00\x00\x01\x00\x00\x00") + (b"\x00" * 20) + b"WAVEDATA"

        schema.pack_into("<II", sdat_header, 0x20, fat_off, len(fat_data))
        schema.pack_into("<II", sdat_header, 0x28, file_off, len(file_data))
        schema.pack_into("<I", sdat_header, 8, 64 + len(fat_data) + len(file_data))

        with open(sdat_path, "wb") as f:
            f.write(sdat_header + fat_data + file_data)

        # Test SDAT info
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "info", sdat_path])
        main()

        # Test SDAT extract
        out_sdat_dir = os.path.join(tmpdir, "sdat_files")
        monkeypatch.setattr("sys.argv", ["miorom", "audio", "extract", sdat_path, "-o", out_sdat_dir])
        main()
        assert os.path.exists(out_sdat_dir)
