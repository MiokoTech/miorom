import pytest

from miorom.platforms.psx.memory_card import (
    CARD_SIZE,
    BLOCK_SIZE,
    FRAME_SIZE,
    PSXBlockState,
    PSXMemoryCard,
    PSXSaveFile,
    calculate_frame_xor,
)
from miorom.graphics.palette import Color, Palette
from miorom.errors import ParseError

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def _create_sample_palette() -> Palette:
    colors = [Color(0, 0, 0, 0)]  # Index 0 transparent
    for i in range(1, 16):
        colors.append(Color(i * 16, (16 - i) * 16, (i * 8) % 256, 255))
    return Palette(colors)


def test_format_blank_card():
    card = PSXMemoryCard.format_blank()
    raw = card.to_bytes()
    assert len(raw) == CARD_SIZE
    assert raw[:2] == b"MC"

    # All frames 0..63 in Block 0 must have valid XOR checksums
    for i in range(64):
        frame = raw[i * FRAME_SIZE : (i + 1) * FRAME_SIZE]
        assert calculate_frame_xor(frame) == frame[127]

    # Check free blocks
    free_blocks = card.get_free_blocks()
    assert free_blocks == list(range(1, 16))
    assert len(card.get_files()) == 0


def test_xor_checksum_validation_and_repair():
    card = PSXMemoryCard.format_blank()
    raw = card.to_bytes()
    
    # Corrupt checksum at Frame 1
    corrupted = bytearray(raw)
    corrupted[1 * FRAME_SIZE + 127] ^= 0xFF
    
    # Checksum is invalid
    frame1 = corrupted[FRAME_SIZE : 2 * FRAME_SIZE]
    assert calculate_frame_xor(frame1) != frame1[127]

    # Load and repair
    repaired_card = PSXMemoryCard.from_bytes(bytes(corrupted))
    repaired_card.repair_checksums()
    fixed_bytes = repaired_card.to_bytes()

    # Verify repaired
    frame1_fixed = fixed_bytes[FRAME_SIZE : 2 * FRAME_SIZE]
    assert calculate_frame_xor(frame1_fixed) == frame1_fixed[127]


def test_inject_and_extract_single_block_save():
    card = PSXMemoryCard.format_blank()
    pal = _create_sample_palette()
    icon_frame = bytes([0x12] * 128)  # 16x16 4bpp dummy pixels
    payload = b"PSX_GAME_SAVE_STATE_DATA_0123456789"

    save = PSXSaveFile(
        filename="BASLUS-00001TEST",
        title="MioROM Test Adventure",
        file_size=len(payload) + 128 + 128,
        block_count=1,
        payload=payload,
        palette=pal,
        icon_bitmaps=[icon_frame],
    )

    start_block = card.inject_file(save)
    assert start_block == 1

    # Re-parse card
    card_bytes = card.to_bytes()
    loaded_card = PSXMemoryCard.from_bytes(card_bytes)
    files = loaded_card.get_files()

    assert len(files) == 1
    loaded_save = files[0]
    assert loaded_save.filename == "BASLUS-00001TEST"
    assert loaded_save.title == "MioROM Test Adventure"
    assert loaded_save.block_count == 1
    assert loaded_save.payload == payload
    assert len(loaded_save.icon_bitmaps) == 1
    assert loaded_save.icon_bitmaps[0] == icon_frame

    # Free blocks should now be 2..15
    assert loaded_card.get_free_blocks() == list(range(2, 16))


def test_inject_multi_block_save():
    card = PSXMemoryCard.format_blank()
    pal = _create_sample_palette()
    icon_frames = [bytes([0x11] * 128), bytes([0x22] * 128)]
    payload = b"X" * 12000  # Multi-block payload > 8KB

    save = PSXSaveFile(
        filename="BAESEP-00002RPG",
        title="Epic Quest 2-Block",
        payload=payload,
        palette=pal,
        icon_bitmaps=icon_frames,
    )

    start_block = card.inject_file(save)
    assert start_block == 1

    loaded = PSXMemoryCard.from_bytes(card.to_bytes())
    files = loaded.get_files()
    assert len(files) == 1
    assert files[0].block_count == 2
    assert files[0].payload == payload

    # Directory entries check
    ent1 = loaded.get_directory_entry(1)
    ent2 = loaded.get_directory_entry(2)
    assert ent1.alloc_state == PSXBlockState.IN_USE_INITIAL
    assert ent1.next_block == 2
    assert ent2.alloc_state == PSXBlockState.IN_USE_LAST
    assert ent2.next_block == 0xFFFF


def test_icon_rgba_and_pil():
    pal = _create_sample_palette()
    icon_frame = bytearray(128)
    # Set top-left pixel (x=0, y=0) to color index 3
    icon_frame[0] = 0x03  # low nibble = 3, high nibble = 0
    
    save = PSXSaveFile(
        filename="TEST",
        title="Icon Test",
        file_size=512,
        block_count=1,
        payload=b"dummy",
        palette=pal,
        icon_bitmaps=[bytes(icon_frame)],
    )

    rgba = save.decode_icon_rgba(0)
    assert len(rgba) == 16 * 16 * 4

    # Top-left pixel RGBA must match color 3
    c3 = pal[3]
    assert rgba[0] == c3.r
    assert rgba[1] == c3.g
    assert rgba[2] == c3.b
    assert rgba[3] == c3.a

    if HAS_PIL:
        img = save.get_icon_image(0)
        assert img is not None
        assert img.size == (16, 16)
        assert img.mode == "RGBA"
        px = img.getpixel((0, 0))
        assert px == (c3.r, c3.g, c3.b, c3.a)


def test_mcs_export_and_import():
    pal = _create_sample_palette()
    save = PSXSaveFile(
        filename="BASLUS-00123MCS",
        title="MCS Export Test",
        payload=b"MCS_PAYLOAD_TEST",
        palette=pal,
        icon_bitmaps=[bytes([0x55] * 128)],
    )

    mcs_bytes = save.to_mcs()
    assert len(mcs_bytes) == FRAME_SIZE + BLOCK_SIZE

    # Re-import from MCS
    imported = PSXSaveFile.from_mcs(mcs_bytes)
    assert imported.filename == "BASLUS-00123MCS"
    assert imported.title == "MCS Export Test"
    assert imported.payload == b"MCS_PAYLOAD_TEST"


def test_delete_save_file():
    card = PSXMemoryCard.format_blank()
    pal = _create_sample_palette()
    save = PSXSaveFile(
        filename="DELETE_ME",
        title="To Be Deleted",
        file_size=1024,
        block_count=1,
        payload=b"DELETE",
        palette=pal,
        icon_bitmaps=[bytes([0] * 128)],
    )

    block = card.inject_file(save)
    assert len(card.get_files()) == 1

    card.delete_file(block)
    # File should no longer be listed
    assert len(card.get_files()) == 0
    # Block 1 should now be considered available again
    assert 1 in card.get_free_blocks()


def test_invalid_card_errors():
    # Wrong size
    with pytest.raises(ParseError, match="Invalid PSX memory card size"):
        PSXMemoryCard(bytearray(1000))

    # Wrong magic
    bad_magic = bytearray(CARD_SIZE)
    bad_magic[:2] = b"XX"
    with pytest.raises(ParseError, match="Invalid memory card header magic"):
        PSXMemoryCard(bad_magic)

    # Out of space
    card = PSXMemoryCard.format_blank()
    pal = _create_sample_palette()
    huge_save = PSXSaveFile(
        filename="HUGE",
        title="Too Big",
        file_size=100000,
        block_count=16,  # Card only has 15 data blocks
        payload=b"",
        palette=pal,
        icon_bitmaps=[bytes(128)],
    )
    with pytest.raises(ValueError, match="Not enough free blocks"):
        card.inject_file(huge_save)
