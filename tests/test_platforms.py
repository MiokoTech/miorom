import os
import struct
import pytest
from miorom.platforms.wii import U8Archive, TPLFile, BRFNTFont


def test_u8_pack_and_extract_roundtrip(tmp_path):
    # Setup test directory tree
    src_dir = tmp_path / "u8_source"
    src_dir.mkdir()
    (src_dir / "file1.txt").write_text("Hello from U8 file 1!", encoding="utf-8")

    sub_dir = src_dir / "textures"
    sub_dir.mkdir()
    (sub_dir / "banner.bin").write_bytes(b"\xDE\xAD\xBE\xEF" * 16)

    arc_path = tmp_path / "test.arc"
    out_dir = tmp_path / "u8_extracted"

    # Pack
    U8Archive.pack(str(src_dir), str(arc_path))
    assert arc_path.exists()
    assert arc_path.stat().st_size > 0

    # List
    entries = U8Archive.list_files(str(arc_path))
    assert len(entries) >= 2
    paths = [e.path for e in entries]
    assert any("file1.txt" in p for p in paths)
    assert any("banner.bin" in p for p in paths)

    # Extract
    extracted = U8Archive.extract_all(str(arc_path), str(out_dir))
    assert len(extracted) == 2

    # Verify contents
    extracted_txt = out_dir / "file1.txt"
    assert extracted_txt.exists()
    assert extracted_txt.read_text(encoding="utf-8") == "Hello from U8 file 1!"

    extracted_bin = out_dir / "textures" / "banner.bin"
    assert extracted_bin.exists()
    assert extracted_bin.read_bytes() == b"\xDE\xAD\xBE\xEF" * 16


def test_tpl_synthetic_decode():
    # Construct a minimal valid 4x4 RGB5A3 TPL file
    w, h = 4, 4
    num_images = 1
    table_offset = 12
    img_hdr_off = 20
    data_off = 56

    # 4x4 RGB5A3 is 1 tile of 16 pixels (32 bytes)
    # Let's create opaque red pixels in RGB555: (0x8000 | (31 << 10)) = 0xFC00
    pixel_val = 0x8000 | (31 << 10)
    raw_tile = struct.pack(">H", pixel_val) * 16

    tpl_bytes = bytearray()
    # TPL Header (12 bytes)
    tpl_bytes.extend(struct.pack(">III", 0x0020AF30, num_images, table_offset))
    # Image table (8 bytes)
    tpl_bytes.extend(struct.pack(">II", img_hdr_off, 0))
    # Image header (36 bytes)
    tpl_bytes.extend(struct.pack(">HHIIIIII", h, w, 5, data_off, 0, 0, 0, 0))
    tpl_bytes.extend(b"\x00" * 8)
    # Pixel data
    tpl_bytes.extend(raw_tile)

    tpl = TPLFile.from_bytes(bytes(tpl_bytes))
    assert len(tpl.images) == 1
    img = tpl.images[0]
    assert img.width == 4
    assert img.height == 4
    assert img.format_name == "RGB5A3"

    rgba = tpl.decode_rgba(0)
    assert len(rgba) == 4 * 4 * 4
    # First pixel should be red (255, 0, 0, 255)
    assert rgba[0] == 255
    assert rgba[1] == 0
    assert rgba[2] == 0
    assert rgba[3] == 255


def test_brfnt_metrics():
    # Construct a minimal synthetic RFNT binary font
    font = BRFNTFont(line_height=20, default_width=10)
    assert font.get_text_width("Hello") == 50

    # Add a custom mapped glyph
    font.char_to_glyph[ord("A")] = 1
    from miorom.platforms.wii.brfnt import CharWidth
    font.glyph_widths[1] = CharWidth(left_bearing=0, glyph_width=12, char_advance=14)

    assert font.has_char("A")
    assert not font.has_char("Z")
    assert font.get_char_width("A") == 14
    assert font.get_char_width("Z") == 10  # default
    assert font.get_text_width("AA") == 28
