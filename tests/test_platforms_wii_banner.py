import math

import pytest

from miorom.audio.wav_codec import WavCodec, WavSound
from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGImage
from miorom.platforms.wii.banner import (
    BNR1_MAGIC,
    BNR2_MAGIC,
    BNS_MAGIC,
    GC_IMAGE_HEIGHT,
    GC_IMAGE_SIZE,
    GC_IMAGE_WIDTH,
    IMD5_MAGIC,
    IMET_MAGIC,
    BannerFile,
    GCBanner,
    GCBannerHeaderStruct,
    IMETHeaderStruct,
    WiiBanner,
    calculate_imet_md5,
    decode_bns_to_wav,
    decode_rgb5a3,
    encode_rgb5a3,
    encode_wav_to_bns,
    unwrap_imd5,
    wrap_imd5,
)
from miorom.platforms.wii.disc import (
    PARTITION_TYPE_DATA,
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
)


def _synthesize_test_wav(duration_secs: float = 0.05, sample_rate: int = 16000) -> bytes:
    """Generates a small valid sine-wave WAV for testing."""
    total_samples = int(duration_secs * sample_rate)
    samples = [
        int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        for i in range(total_samples)
    ]
    sound = WavSound(
        samples=samples,
        sample_rate=sample_rate,
        channels=1,
        bits_per_sample=16,
    )
    return WavCodec.encode(sound)


def test_imet_header_and_md5():
    hdr = IMETHeaderStruct(
        magic=IMET_MAGIC,
        hash_size=0x0600,
        version=3,
        icon_size=1024,
        banner_size=4096,
        sound_size=2048,
    )
    raw = hdr.to_bytes()
    assert len(raw) == 0x600  # 1536 bytes
    assert raw[0x40:0x44] == IMET_MAGIC

    # Calculate MD5
    digest = calculate_imet_md5(raw)
    assert len(digest) == 16
    assert digest != b"\x00" * 16

    # Update crypto and verify
    raw_with_md5 = raw[:0x5F0] + digest
    digest2 = calculate_imet_md5(raw_with_md5)
    assert digest2 == digest


def test_imd5_wrap_unwrap():
    payload = b"TEST_AUDIO_OR_TEXTURE_PAYLOAD_BYTES"
    wrapped = wrap_imd5(payload)
    assert len(wrapped) == 32 + len(payload)
    assert wrapped[:4] == IMD5_MAGIC

    unwrapped = unwrap_imd5(wrapped)
    assert unwrapped == payload

    # Non-IMD5 pass-through
    assert unwrap_imd5(b"RAW_DATA_WITHOUT_HEADER") == b"RAW_DATA_WITHOUT_HEADER"


def test_rgb5a3_codec_roundtrip():
    # Construct 96x32 RGBA buffer
    rgba = bytearray(GC_IMAGE_WIDTH * GC_IMAGE_HEIGHT * 4)
    for y in range(GC_IMAGE_HEIGHT):
        for x in range(GC_IMAGE_WIDTH):
            idx = (y * GC_IMAGE_WIDTH + x) * 4
            rgba[idx] = (x * 255 // GC_IMAGE_WIDTH)
            rgba[idx + 1] = (y * 255 // GC_IMAGE_HEIGHT)
            rgba[idx + 2] = 128
            rgba[idx + 3] = 255 if y < 16 else 128  # opaque and translucent

    encoded = encode_rgb5a3(bytes(rgba), GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT)
    assert len(encoded) == GC_IMAGE_SIZE

    decoded = decode_rgb5a3(encoded, GC_IMAGE_WIDTH, GC_IMAGE_HEIGHT)
    assert len(decoded) == len(rgba)

    # Convert through PNGImage
    png_img = PNGImage(
        width=GC_IMAGE_WIDTH,
        height=GC_IMAGE_HEIGHT,
        color_type=6,
        bit_depth=8,
        pixels=decoded,
    )
    assert png_img.width == 96
    assert png_img.height == 32


def test_gc_banner_parsing_and_mutation():
    gc_banner = GCBanner(magic=BNR2_MAGIC)
    assert gc_banner.is_multi_language is True

    # Modify titles
    gc_banner.set_title(
        title="Super Mario Sunshine",
        lang_idx=0,
        full_title="Super Mario Sunshine Deluxe",
        company="Nintendo",
        description="A tropical adventure.",
    )
    assert gc_banner.get_title(0) == "Super Mario Sunshine"

    raw_bytes = gc_banner.to_bytes()
    assert len(raw_bytes) == 32 + GC_IMAGE_SIZE + 6 * 320  # 8096 bytes

    reparsed = GCBanner.from_bytes(raw_bytes)
    assert reparsed.magic == BNR2_MAGIC
    assert reparsed.get_title(0) == "Super Mario Sunshine"
    assert reparsed.comments[0].full_title == "Super Mario Sunshine Deluxe"
    assert reparsed.comments[0].short_company == "Nintendo"
    assert reparsed.comments[0].description == "A tropical adventure."

    # Image manipulation
    test_img = PNGImage(
        width=96,
        height=32,
        color_type=6,
        bit_depth=8,
        pixels=b"\xff\x00\x00\xff" * (96 * 32),
    )
    reparsed.set_image(test_img)
    re_encoded_bytes = reparsed.to_bytes()
    re_reparsed = GCBanner.from_bytes(re_encoded_bytes)
    out_img = re_reparsed.get_image()
    assert out_img.width == 96
    assert out_img.height == 32


def test_bns_audio_codec_roundtrip():
    wav_bytes = _synthesize_test_wav(duration_secs=0.05, sample_rate=16000)
    bns_data = encode_wav_to_bns(wav_bytes, loop=True)
    assert bns_data.startswith(BNS_MAGIC)

    decoded_wav = decode_bns_to_wav(bns_data)
    sound = WavCodec.decode(decoded_wav)
    assert sound.sample_rate == 16000
    assert sound.channels == 1
    assert len(sound.samples) > 0
    # Decoded sine wave must have dynamic range (not silence)
    assert max(abs(s) for s in sound.samples) > 5000


def test_bns_specification_compliance_and_stereo():
    from miorom.audio.dsp_adpcm import DEFAULT_DSP_COEFFS
    from miorom.core.binary import BinaryReader

    # 1. Mono WAV
    mono_wav = _synthesize_test_wav(duration_secs=0.04, sample_rate=16000)
    bns_mono = encode_wav_to_bns(mono_wav, loop=False)

    # Locate INFO chunk
    info_idx = bns_mono.find(b"INFO")
    assert info_idx != -1
    info_sz = BinaryReader.unpack_u32(bns_mono, info_idx + 4, endian=">")
    info_payload = bns_mono[info_idx + 8 : info_idx + info_sz]

    # Verify standard Nintendo BNS header fields
    assert info_payload[0] == 0  # Codec 0 = Nintendo BNS DSP-ADPCM
    assert info_payload[1] == 0  # Loop flag
    assert info_payload[2] == 1  # Channels
    assert BinaryReader.unpack_u16(info_payload, 4, endian=">") == 16000  # Sample rate

    # Verify Channel Info pointer at 0x18
    ch_info_ptr = BinaryReader.unpack_u32(info_payload, 0x18, endian=">")
    assert ch_info_ptr == 0x1C  # Immediately follows the 4-byte pointer table

    # Verify 12-byte Channel Info struct at 0x1C
    ch_data_off = BinaryReader.unpack_u32(info_payload, 0x1C, endian=">")
    ch_dsp_off = BinaryReader.unpack_u32(info_payload, 0x20, endian=">")
    reserved = BinaryReader.unpack_u32(info_payload, 0x24, endian=">")
    assert ch_data_off == 0
    assert ch_dsp_off == 0x28  # 0x1C + 12 = 0x28
    assert reserved == 0

    # Verify 16 coefficients at ch_dsp_off match DEFAULT_DSP_COEFFS
    coeffs = [
        BinaryReader.unpack_s16(info_payload, ch_dsp_off + k * 2, endian=">")
        for k in range(16)
    ]
    assert coeffs == list(DEFAULT_DSP_COEFFS)

    # 2. Stereo WAV
    total_samples = 800
    stereo_samples = []
    for i in range(total_samples):
        # Left: 440Hz sine, Right: 880Hz sine
        s_left = int(14000 * math.sin(2 * math.pi * 440 * i / 16000))
        s_right = int(14000 * math.sin(2 * math.pi * 880 * i / 16000))
        stereo_samples.extend([s_left, s_right])

    stereo_wav = WavCodec.encode(WavSound(
        samples=stereo_samples,
        sample_rate=16000,
        channels=2,
        bits_per_sample=16,
    ))
    bns_stereo = encode_wav_to_bns(stereo_wav, loop=True)
    decoded_stereo = decode_bns_to_wav(bns_stereo)
    sound_stereo = WavCodec.decode(decoded_stereo)
    assert sound_stereo.channels == 2
    assert sound_stereo.sample_rate == 16000
    assert len(sound_stereo.samples) == total_samples * 2

    # 3. Authentic & legacy codec 2 decoding
    # Mutate codec byte in bns_mono from 0 to 2
    bns_codec2 = bytearray(bns_mono)
    bns_codec2[info_idx + 8] = 2
    decoded_codec2 = decode_bns_to_wav(bytes(bns_codec2))
    sound_codec2 = WavCodec.decode(decoded_codec2)
    assert sound_codec2.channels == 1
    assert len(sound_codec2.samples) > 0


def test_wii_banner_full_roundtrip(tmp_path):
    wav_bytes = _synthesize_test_wav(duration_secs=0.04, sample_rate=16000)

    wii_banner = WiiBanner()
    wii_banner.set_title("Mario Kart Wii", lang="en")
    wii_banner.set_title("マリオカートWii", lang="jp")
    wii_banner.set_title("Mario Kart Wii FR", lang="fr")
    wii_banner.set_title("Mario Kart Wii DE", lang="de")

    wii_banner.banner_bin = b"MOCK_BANNER_BRLYT_CONTENT"
    wii_banner.icon_bin = b"MOCK_ICON_BRLYT_CONTENT"
    wii_banner.set_sound_wav(wav_bytes)

    assert wii_banner.get_title("en") == "Mario Kart Wii"
    assert wii_banner.get_title("jp") == "マリオカートWii"

    all_titles = wii_banner.get_all_titles()
    assert all_titles["en"] == "Mario Kart Wii"
    assert all_titles["jp"] == "マリオカートWii"

    # Serialize to bytes
    bnr_raw = wii_banner.to_bytes()
    assert bnr_raw[0x40:0x44] == IMET_MAGIC
    assert len(bnr_raw) > 0x600

    # Parse back
    reparsed = WiiBanner.from_bytes(bnr_raw)
    assert reparsed.get_title("en") == "Mario Kart Wii"
    assert reparsed.get_title("jp") == "マリオカートWii"
    assert reparsed.get_title("fr") == "Mario Kart Wii FR"
    assert reparsed.get_title("de") == "Mario Kart Wii DE"

    # Verify audio decodes
    extracted_wav = reparsed.get_sound_wav()
    sound = WavCodec.decode(extracted_wav)
    assert sound.sample_rate == 16000

    # File IO test
    out_file = tmp_path / "opening.bnr"
    reparsed.save(out_file)
    assert out_file.exists()

    loaded = WiiBanner.from_bytes(out_file.read_bytes())
    assert loaded.get_title("en") == "Mario Kart Wii"

    # Test error on invalid language code
    with pytest.raises(ValueError, match="Unknown Wii language code"):
        wii_banner.set_title("Invalid", lang="invalid_code")


def test_banner_file_factory():
    # GameCube BNR1
    gc1_data = GCBannerHeaderStruct(magic=BNR1_MAGIC).to_bytes() + b"\x00" * (GC_IMAGE_SIZE + 320)
    bf1 = BannerFile.from_bytes(gc1_data)
    assert isinstance(bf1, GCBanner)
    assert bf1.magic == BNR1_MAGIC

    # GameCube BNR2
    gc2_data = GCBannerHeaderStruct(magic=BNR2_MAGIC).to_bytes() + b"\x00" * (GC_IMAGE_SIZE + 6 * 320)
    bf2 = BannerFile.from_bytes(gc2_data)
    assert isinstance(bf2, GCBanner)
    assert bf2.magic == BNR2_MAGIC

    # Wii Opening.bnr
    wii_banner = WiiBanner()
    wii_banner.set_title("Test Title", lang="en")
    wii_bytes = wii_banner.to_bytes()
    bf_wii = BannerFile.from_bytes(wii_bytes)
    assert isinstance(bf_wii, WiiBanner)
    assert bf_wii.get_title("en") == "Test Title"

    # Corrupt
    with pytest.raises(ParseError, match="Unrecognized banner format"):
        BannerFile.from_bytes(b"INVALID_MAGIC_12345")


def test_wii_disc_banner_integration():
    # Build minimal WiiDisc with partition containing opening.bnr
    from miorom.rom.handlers.wii import _create_default_ticket_and_tmd

    ticket, tmd, title_key = _create_default_ticket_and_tmd()
    part = WiiPartition(
        partition_offset=0x50000,
        partition_type=PARTITION_TYPE_DATA,
        ticket=ticket,
        tmd=tmd,
        title_key=title_key,
        data_offset=0x70000,
        data_size=0x100000,
        h3_offset=0x51000,
    )

    wii_banner = WiiBanner()
    wii_banner.set_title("Zelda: Twilight Princess", lang="en")
    part.files["files/opening.bnr"] = wii_banner.to_bytes()

    disc = WiiDisc(
        header=WiiDiscHeader(
            game_id="RZDE",
            maker_code="01",
            disc_number=0,
            version=1,
            audio_streaming=False,
            stream_buf_size=0,
            magic=0x5D1C9EA3,
            gc_magic=0xC2339F3D,
            game_title="The Legend of Zelda",
        ),
        partitions=[part],
    )

    banner_found = disc.get_banner()
    assert banner_found is not None
    assert isinstance(banner_found, WiiBanner)
    assert banner_found.get_title("en") == "Zelda: Twilight Princess"

    # Test set_banner
    banner_found.set_title("Zelda: Twilight Princess (Indonesian)", lang="en")
    disc.set_banner(banner_found)

    updated_banner = disc.get_banner()
    assert updated_banner is not None
    assert updated_banner.get_title("en") == "Zelda: Twilight Princess (Indonesian)"


def test_gc_banner_european_bnr2_multilingual_encodings():
    banner = GCBanner(magic=BNR2_MAGIC)
    # European languages with accents
    banner.set_title("Pokémon Colosseum", 0, full_title="Pokémon Colosseum Special Edition")
    banner.set_title("Über Mario Kart", 1, full_title="Über Mario Kart GC", description="Ein tolles Spiel für alle.")
    banner.set_title("Édition Française", 2, company="Société Française")
    banner.set_title("Español Aventura", 3, description="Año nuevo, juego nuevo.")

    raw = banner.to_bytes()
    loaded = GCBanner.from_bytes(raw)

    assert loaded.get_title(0) == "Pokémon Colosseum"
    assert loaded.comments[0].full_title == "Pokémon Colosseum Special Edition"
    assert loaded.get_title(1) == "Über Mario Kart"
    assert loaded.comments[1].description == "Ein tolles Spiel für alle."
    assert loaded.get_title(2) == "Édition Française"
    assert loaded.comments[2].short_company == "Société Française"
    assert loaded.get_title(3) == "Español Aventura"
    assert loaded.comments[3].description == "Año nuevo, juego nuevo."


def test_gc_banner_japanese_bnr1_shift_jis():
    banner = GCBanner(magic=BNR1_MAGIC)
    banner.set_title("ゼルダの伝説", 0, full_title="ゼルダの伝説 風のタクト", company="任天堂")

    raw = banner.to_bytes()
    loaded = GCBanner.from_bytes(raw)

    assert loaded.get_title(0) == "ゼルダの伝説"
    assert loaded.comments[0].full_title == "ゼルダの伝説 風のタクト"
    assert loaded.comments[0].short_company == "任天堂"


def test_gc_banner_png_export_and_resilient_set_image(tmp_path):
    banner = GCBanner(magic=BNR1_MAGIC)
    # Test zero-dependency PNG export
    png_path = tmp_path / "gc_icon.png"
    banner.save_image_png(str(png_path))
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Test setting image from PNG file path
    banner.set_image(str(png_path))
    reloaded_img = banner.get_image()
    assert reloaded_img.width == 96
    assert reloaded_img.height == 32


def test_wii_banner_language_aliases_and_safe_utf16():
    banner = WiiBanner()
    # Language aliases
    banner.set_title("マリオギャラクシー", lang="japanese")
    banner.set_title("Mario Galaxy", lang="english")
    banner.set_title("Mario Galaxie (DE)", lang="german")

    assert banner.get_title("ja") == "マリオギャラクシー"
    assert banner.get_title(0) == "マリオギャラクシー"
    assert banner.get_title("us") == "Mario Galaxy"
    assert banner.get_title(1) == "Mario Galaxy"
    assert banner.get_title("ge") == "Mario Galaxie (DE)"

    # Safe oversized UTF-16 truncation
    long_title = "Super Mario Galaxy Long Title Testing " * 3
    banner.set_title(long_title, lang="en")
    raw = banner.to_bytes()
    loaded = WiiBanner.from_bytes(raw)
    assert len(loaded.get_title("en")) <= 41
    assert loaded.get_title("en") in long_title

