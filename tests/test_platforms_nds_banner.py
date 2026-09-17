import pytest
from PIL import Image

from miorom.core.checksum import RetroChecksum
from miorom.errors import ParseError
from miorom.platforms.nds.banner import (
    NDSBanner,
    NDSBannerHeaderStruct,
    bgr555_to_rgb,
    rgb_to_bgr555,
)
from miorom.platforms.nds.rom import NDSHeaderStruct, NDSRom


def test_bgr555_color_conversions():
    # Pure red
    val_red = rgb_to_bgr555(255, 0, 0)
    assert val_red == 0x1F
    r, g, b = bgr555_to_rgb(val_red)
    assert r == 255 and g == 0 and b == 0

    # Pure green
    val_green = rgb_to_bgr555(0, 255, 0)
    assert val_green == (0x1F << 5)
    r, g, b = bgr555_to_rgb(val_green)
    assert r == 0 and g == 255 and b == 0

    # Pure blue
    val_blue = rgb_to_bgr555(0, 0, 255)
    assert val_blue == (0x1F << 10)
    r, g, b = bgr555_to_rgb(val_blue)
    assert r == 0 and g == 0 and b == 255


def test_banner_synthetic_roundtrip():
    banner = NDSBanner(version=1)
    banner.set_title("Super Mario 64 DS\nNintendo", language="English")
    banner.set_title("スーパーマリオ64DS\n任天堂", language="Japanese")
    banner.set_title("Super Mario 64 DS (FR)\nNintendo", language="French")

    # Set some distinct palette colors
    palette = [(0, 0, 0)] + [(i * 16, 255 - i * 16, 128) for i in range(1, 16)]
    banner.icon_palette = palette

    # Create a test pattern on the 32x32 icon (diagonal stripes)
    pixels = [[(x + y) % 16 for x in range(32)] for y in range(32)]
    banner.set_pixel_indices(pixels)

    # Serialize to binary bytes
    raw = banner.to_bytes(recalc_crc=True)
    assert len(raw) == 0x840

    # Check CRC16 in header
    hdr = NDSBannerHeaderStruct.from_bytes(raw, offset=0)
    assert hdr.version == 1
    expected_crc = RetroChecksum.crc16_modbus(raw[0x20:0x840])
    assert hdr.crc_v1 == expected_crc
    assert banner.is_crc_valid()

    # Deserialize back
    loaded = NDSBanner.from_bytes(raw)
    assert loaded.version == 1
    assert loaded.get_title("English") == "Super Mario 64 DS\nNintendo"
    assert loaded.get_title("Japanese") == "スーパーマリオ64DS\n任天堂"
    assert loaded.get_title("French") == "Super Mario 64 DS (FR)\nNintendo"
    assert loaded.get_title("Spanish") == ""

    # Verify pixel grid matches exactly
    loaded_pixels = loaded.get_pixel_indices()
    assert loaded_pixels == pixels


def test_banner_image_conversion():
    banner = NDSBanner(version=1)

    # Create a 32x32 RGBA test image: top half transparent, bottom half red and blue
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for y in range(16, 32):
        for x in range(32):
            if x < 16:
                img.putpixel((x, y), (255, 0, 0, 255))   # Red
            else:
                img.putpixel((x, y), (0, 0, 255, 255))   # Blue

    banner.set_image(img)

    # Render back to image
    rendered = banner.to_image()
    assert rendered.size == (32, 32)
    assert rendered.mode == "RGBA"

    # Top pixel should be transparent (alpha = 0)
    p_top = rendered.getpixel((8, 8))
    assert p_top[3] == 0

    # Bottom left should be red and opaque
    p_red = rendered.getpixel((8, 24))
    assert p_red[0] == 255 and p_red[1] == 0 and p_red[2] == 0 and p_red[3] == 255

    # Bottom right should be blue and opaque
    p_blue = rendered.getpixel((24, 24))
    assert p_blue[0] == 0 and p_blue[1] == 0 and p_blue[2] == 255 and p_blue[3] == 255

    # Check raw RGBA bytes length
    rgba_bytes = banner.to_rgba_bytes()
    assert len(rgba_bytes) == 32 * 32 * 4


def test_banner_multilingual_and_versions():
    banner = NDSBanner(version=1)
    banner.set_title("Castlevania: Dawn of Sorrow", "English")

    # Setting Chinese title should automatically update version to 2
    banner.set_title("恶魔城：苍月十字架", "Chinese")
    assert banner.version == 2
    raw_v2 = banner.to_bytes()
    assert len(raw_v2) == 0x940
    assert banner.is_crc_valid()

    # Setting Korean title should automatically update version to 3
    banner.set_title("악마성 드라큘라 창월의 십자가", "Korean")
    assert banner.version == 3
    raw_v3 = banner.to_bytes()
    assert len(raw_v3) == 0xA40
    assert banner.is_crc_valid()

    # Load back v3
    loaded_v3 = NDSBanner.from_bytes(raw_v3)
    assert loaded_v3.version == 3
    assert loaded_v3.get_title("Korean") == "악마성 드라큘라 창월의 십자가"
    assert loaded_v3.get_title("Chinese") == "恶魔城：苍月十字架"
    assert loaded_v3.get_title("English") == "Castlevania: Dawn of Sorrow"


def test_banner_crc_tampering_detection():
    banner = NDSBanner(version=1)
    banner.set_title("Pokemon Platinum Version", "English")
    raw = bytearray(banner.to_bytes())

    # Initial CRC should be valid
    loaded = NDSBanner.from_bytes(raw)
    assert loaded.is_crc_valid()

    # Tamper with English title string in raw binary
    raw[0x340] = ord("X")
    loaded_tampered = NDSBanner.from_bytes(raw)
    assert not loaded_tampered.is_crc_valid()


def test_banner_rom_integration():
    # Build synthetic ROM with banner
    banner = NDSBanner(version=1)
    banner.set_title("Chrono Trigger DS\nSquare Enix", "English")
    banner_raw = banner.to_bytes()

    rom_buf = bytearray(0x8000)
    hdr = NDSHeaderStruct(
        game_title="CHRONOTRIGGER",
        game_code="YQTE",
        maker_code="01",
        unit_code=0,
        arm9_offset=0x1000,
        arm9_entry_address=0x02000000,
        arm9_ram_address=0x02000000,
        arm9_size=0x100,
        arm7_offset=0x1200,
        arm7_entry_address=0x02380000,
        arm7_ram_address=0x02380000,
        arm7_size=0x100,
        fnt_offset=0x1400,
        fnt_size=0x100,
        fat_offset=0x1600,
        fat_size=0x100,
        arm9_overlay_offset=0,
        arm9_overlay_size=0,
        arm7_overlay_offset=0,
        arm7_overlay_size=0,
        banner_offset=0x2000,
        header_crc=0,
    )
    rom_buf[:len(hdr.to_bytes())] = hdr.to_bytes()
    rom_buf[0x2000 : 0x2000 + len(banner_raw)] = banner_raw

    rom = NDSRom(bytes(rom_buf))
    assert rom.get_banner_title("English") == "Chrono Trigger DS\nSquare Enix"

    # Modify banner through NDSRom
    parsed_banner = rom.get_banner()
    assert parsed_banner is not None
    parsed_banner.set_title("Chrono Trigger (Indonesian Translation)\nMiokoROM", "English")
    rom.set_banner(parsed_banner)

    # Verify updated title in ROM
    assert rom.get_banner_title("English") == "Chrono Trigger (Indonesian Translation)\nMiokoROM"


def test_banner_error_handling():
    # Truncated data
    with pytest.raises(ParseError, match="Invalid NDS banner size"):
        NDSBanner.from_bytes(b"short data")


def test_banner_dsi_extended_data_alignment_and_crc():
    # Construct a DSi Banner (version 0x0103) with 4480 bytes of animated data
    dsi_anim_payload = b"\x37" * 4480
    banner = NDSBanner(
        version=0x0103,
        dsi_extended_data=dsi_anim_payload,
    )
    banner.set_title("Chrono Trigger DSi", "English")
    banner.set_title("クロノ・トリガー DSi", "Japanese")
    banner.set_title("超时空之轮 DSi", "Chinese")
    banner.set_title("크로노 트리거 DSi", "Korean")

    raw = banner.to_bytes(recalc_crc=True)
    assert len(raw) == 0x23C0  # Standard DSi banner size: 9152 bytes

    # Verify header CRC fields
    hdr = NDSBannerHeaderStruct.from_bytes(raw, offset=0)
    assert hdr.version == 0x0103
    assert hdr.crc_v1 == RetroChecksum.crc16_modbus(raw[0x20:0x840])
    assert hdr.crc_v2 == RetroChecksum.crc16_modbus(raw[0x20:0x940])
    assert hdr.crc_v3 == RetroChecksum.crc16_modbus(raw[0x20:0xA40])

    # Check that 0x0A40..0x1240 is 0x800 bytes of zeros (reserved padding)
    assert raw[0xA40:0x1240] == b"\x00" * 0x800

    # Check that DSi animated payload is placed at offset 0x1240..0x23C0
    assert raw[0x1240:0x23C0] == dsi_anim_payload

    # Check crc_dsi calculation
    expected_crc_dsi = RetroChecksum.crc16_modbus(dsi_anim_payload)
    assert hdr.crc_dsi == expected_crc_dsi
    assert banner.is_crc_valid()

    # Load back and verify clean extraction (stripping 0x800 zeros)
    loaded = NDSBanner.from_bytes(raw)
    assert loaded.version == 0x0103
    assert loaded.dsi_extended_data == dsi_anim_payload
    assert loaded.get_title("Korean") == "크로노 트리거 DSi"
    assert loaded.get_title("Chinese") == "超时空之轮 DSi"
    assert loaded.get_title("English") == "Chrono Trigger DSi"
    assert loaded.is_crc_valid()
    assert loaded.to_bytes() == raw

    # Tampering with DSi payload must fail CRC validation
    tampered = bytearray(raw)
    tampered[0x1500] ^= 0xFF
    loaded_tampered = NDSBanner.from_bytes(tampered)
    assert not loaded_tampered.is_crc_valid()


def test_banner_zero_dependency_png_export_and_injection(tmp_path):
    from miorom.graphics.png_codec import PNGCodec

    banner = NDSBanner(version=1)
    # Create top half transparent, bottom-left red, bottom-right blue
    rgba_in = bytearray(32 * 32 * 4)
    for y in range(32):
        for x in range(32):
            idx = (y * 32 + x) * 4
            if y < 16:
                rgba_in[idx : idx + 4] = b"\x00\x00\x00\x00"
            elif x < 16:
                rgba_in[idx : idx + 4] = b"\xff\x00\x00\xff"  # Red
            else:
                rgba_in[idx : idx + 4] = b"\x00\x00\xff\xff"  # Blue

    banner.set_image(bytes(rgba_in))

    # Export to PNG bytes without PIL
    png_bytes = banner.to_png_bytes()
    assert png_bytes.startswith(PNGCodec.PNG_SIGNATURE)

    # Decode with pure-Python PNGCodec
    decoded = PNGCodec.decode(png_bytes)
    assert decoded.width == 32
    assert decoded.height == 32

    # Save to disk
    out_file = tmp_path / "banner_icon.png"
    banner.save_icon_png(out_file)
    assert out_file.exists()
    assert out_file.read_bytes().startswith(PNGCodec.PNG_SIGNATURE)

    # Inject PNG bytes into a fresh banner
    new_banner = NDSBanner(version=1)
    new_banner.set_image(png_bytes)
    assert new_banner.to_rgba_bytes() == banner.to_rgba_bytes()

    # Inject from file path into fresh banner
    file_banner = NDSBanner(version=1)
    file_banner.set_image(str(out_file))
    assert file_banner.to_rgba_bytes() == banner.to_rgba_bytes()


def test_banner_dsi_rom_extraction(tmp_path):
    from miorom.platforms.nds.rom import extract_rom

    banner = NDSBanner(version=0x0103, dsi_extended_data=b"\x99" * 4480)
    banner.set_title("DSi ROM Game", "English")
    raw_banner = banner.to_bytes()
    assert len(raw_banner) == 0x23C0

    rom_buf = bytearray(0x8000)
    hdr = NDSHeaderStruct(
        game_title="DSIROMGAME",
        game_code="KDSE",
        maker_code="01",
        unit_code=2,
        arm9_offset=0x1000,
        arm9_entry_address=0x02000000,
        arm9_ram_address=0x02000000,
        arm9_size=0x100,
        arm7_offset=0x1200,
        arm7_entry_address=0x02380000,
        arm7_ram_address=0x02380000,
        arm7_size=0x100,
        fnt_offset=0x1400,
        fnt_size=0x100,
        fat_offset=0x1600,
        fat_size=0x100,
        arm9_overlay_offset=0,
        arm9_overlay_size=0,
        arm7_overlay_offset=0,
        arm7_overlay_size=0,
        banner_offset=0x2000,
        header_crc=0,
    )
    rom_buf[:len(hdr.to_bytes())] = hdr.to_bytes()
    rom_buf[0x2000 : 0x2000 + len(raw_banner)] = raw_banner

    rom_path = tmp_path / "dsi_test.nds"
    rom_path.write_bytes(rom_buf)

    extract_dir = tmp_path / "extracted"
    extract_rom(str(rom_path), str(extract_dir))

    extracted_banner = extract_dir / "banner.bin"
    assert extracted_banner.exists()
    assert len(extracted_banner.read_bytes()) == 0x23C0
    loaded_extracted = NDSBanner.from_bytes(extracted_banner.read_bytes())
    assert loaded_extracted.version == 0x0103
    assert loaded_extracted.get_title("English") == "DSi ROM Game"


def test_banner_opaque_black_preservation():
    banner = NDSBanner(version=1)
    # 32x32 image where (0, 0) is opaque black (0, 0, 0, 255)
    # and (1, 0) is transparent (0, 0, 0, 0)
    rgba = bytearray(32 * 32 * 4)
    rgba[0] = 0
    rgba[1] = 0
    rgba[2] = 0
    rgba[3] = 255  # Opaque black

    banner.set_image(bytes(rgba))
    pixels = banner.get_pixel_indices()

    # Opaque black must NOT be mapped to index 0 (which is hardware transparent)
    assert pixels[0][0] != 0
    assert pixels[0][1] == 0

    # Decoded RGBA must preserve alpha 255 for opaque black
    out_rgba = banner.to_rgba_bytes()
    assert out_rgba[0] == 0
    assert out_rgba[1] == 0
    assert out_rgba[2] == 0
    assert out_rgba[3] == 255

    # Transparent pixel must have alpha 0
    assert out_rgba[7] == 0


def test_banner_language_index_bounds_and_auto_elevation():
    banner = NDSBanner(version=1)

    # Invalid language index must raise IndexError
    with pytest.raises(IndexError, match="out of range"):
        banner.get_title(-1)
    with pytest.raises(IndexError, match="out of range"):
        banner.set_title("Fail", 8)

    # Creating banner with Korean in titles dict directly must auto-elevate to v3
    korean_banner = NDSBanner(version=1, titles={7: "한국어 게임"})
    korean_raw = korean_banner.to_bytes()
    assert len(korean_raw) == 0xA40
    assert korean_banner.version == 3
    assert korean_banner.is_crc_valid()

    reloaded = NDSBanner.from_bytes(korean_raw)
    assert reloaded.version == 3
    assert reloaded.get_title(7) == "한국어 게임"


def test_banner_oversized_title_safe_utf16_truncation():
    banner = NDSBanner(version=1)
    # 300 characters exceeds 254 bytes
    long_title = "A" * 300
    banner.set_title(long_title, 1)

    raw = banner.to_bytes()
    loaded = NDSBanner.from_bytes(raw)
    # Must be cleanly truncated without decoding error
    assert loaded.get_title(1) == "A" * 127
    assert loaded.is_crc_valid()


def test_banner_handler_dsi_extraction(tmp_path):
    from miorom.rom.handlers.nds import NDSRomHandler

    handler = NDSRomHandler()
    banner = NDSBanner(version=0x0103, dsi_extended_data=b"\x42" * 4480)
    banner.set_title("Handler DSi Test", "English")
    banner_raw = banner.to_bytes()
    assert len(banner_raw) == 0x23C0

    rom_buf = bytearray(0x8000)
    hdr = NDSHeaderStruct(
        game_title="DSIHANDLER",
        game_code="KDSH",
        maker_code="01",
        unit_code=2,
        arm9_offset=0x1000,
        arm9_entry_address=0x02000000,
        arm9_ram_address=0x02000000,
        arm9_size=0x100,
        arm7_offset=0x1200,
        arm7_entry_address=0x02380000,
        arm7_ram_address=0x02380000,
        arm7_size=0x100,
        fnt_offset=0x1400,
        fnt_size=0x100,
        fat_offset=0x1600,
        fat_size=0x100,
        banner_offset=0x2000,
        header_crc=0,
    )
    rom_buf[:len(hdr.to_bytes())] = hdr.to_bytes()
    rom_buf[0x2000 : 0x2000 + len(banner_raw)] = banner_raw

    out_dir = tmp_path / "handler_extract"
    handler.unpack(bytes(rom_buf), str(out_dir))

    extracted_banner = out_dir / "sys" / "banner.bin"
    assert extracted_banner.exists()
    assert len(extracted_banner.read_bytes()) == 0x23C0
    loaded_banner = NDSBanner.from_bytes(extracted_banner.read_bytes())
    assert loaded_banner.version == 0x0103
    assert loaded_banner.get_title("English") == "Handler DSi Test"


