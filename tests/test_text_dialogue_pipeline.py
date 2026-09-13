import struct
import pytest

from miorom.text.charmap import CharMap
from miorom.text.tokenizer import ControlCodeDef, ControlCodeSchema, ControlCodeTokenizer
from miorom.text.paginator import SmartAutoPaginator, PaginationConfig
from miorom.text.po_handler import PoHandler
from miorom.script.dialogue_dissector import DialogueDissector, DialogueBlock, DialogueEntry
from miorom.text.japanese_charmap import JapaneseCharMapMiner, HIRAGANA_FULL
from miorom.compression.text_compression_hunter import TextCompressionHunter
from miorom.graphics.tilemap import Tilemap, TilemapEntry
from miorom.graphics.tilemap_dissector import TilemapDissector


def test_control_code_tokenizer_charmap_and_brackets():
    # Setup custom character map
    charmap = CharMap()
    charmap.add_mapping(b"\x10", "A")
    charmap.add_mapping(b"\x11", "B")
    charmap.add_mapping(b"\x12", "C")
    charmap.add_mapping(b"\x20", " ")

    # Setup control code schema with brackets
    schema = ControlCodeSchema(
        codes=[
            ControlCodeDef(byte_id=0x01, name="NL", bracket="[]"),
            ControlCodeDef(byte_id=0x05, name="COLOR", arg_bytes=1, bracket="[]"),
            ControlCodeDef(byte_id=0x06, name="WAIT", arg_bytes=2, arg_endian="<", bracket="[]"),
        ],
        terminator=b"\x00",
    )

    # Encode text with custom charmap and control tags
    text = "A[COLOR:2] B[WAIT:30][NL]C"
    raw = ControlCodeTokenizer.encode(text, schema=schema, charmap=charmap)

    # Expected: 'A' (0x10), COLOR 2 (0x05, 0x02), ' ' (0x20), 'B' (0x11), WAIT 30 (0x06, 0x1E, 0x00), NL (0x01), 'C' (0x12), terminator (0x00)
    expected = b"\x10\x05\x02\x20\x11\x06\x1E\x00\x01\x12\x00"
    assert raw == expected

    # Decode back
    decoded = ControlCodeTokenizer.decode(raw, schema=schema, charmap=charmap)
    assert decoded == "A[COLOR:02] B[WAIT:1E00][NL]C"

    # Test validation
    errors = ControlCodeTokenizer.validate("Valid text [COLOR:1]", schema=schema)
    assert len(errors) == 0

    errors_unclosed = ControlCodeTokenizer.validate("Text with [COLOR:1 unclosed", schema=schema)
    assert len(errors_unclosed) == 1
    assert "Unclosed" in errors_unclosed[0]

    errors_unknown = ControlCodeTokenizer.validate("Text with [UNKNOWN] tag", schema=schema)
    assert len(errors_unknown) == 1
    assert "Unknown control code" in errors_unknown[0]


def test_dialogue_dissector_with_schema_and_pagination():
    rom = bytearray(0x2000)

    # Setup schema
    schema = ControlCodeSchema(
        codes=[
            ControlCodeDef(byte_id=0x01, name="NL", bracket="[]"),
            ControlCodeDef(byte_id=0x05, name="COLOR", arg_bytes=1, bracket="[]"),
            ControlCodeDef(byte_id=0x09, name="PAGE", bracket="[]"),
        ],
        terminator=b"\x00",
    )

    # Write dialogue payload: "Hero[COLOR:1] wake up[NL]now!\x00"
    dialogue_raw = b"Hero\x05\x01 wake up\x01now!\x00"
    target_offset = 0x0300
    rom[target_offset : target_offset + len(dialogue_raw)] = dialogue_raw

    # Write 32-bit LE pointer table at 0x0100
    table_offset = 0x0100
    rom[table_offset : table_offset + 4] = struct.pack("<I", target_offset)

    # Extract dialogue block using schema
    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=1,
        pointer_size=4,
        endian="<",
        base_address=0,
        encoding="ascii",
        schema=schema,
        block_id="intro",
    )

    assert len(block.entries) == 1
    entry = block.entries[0]
    assert entry.text == "Hero[COLOR:01] wake up[NL]now!"
    assert "COLOR" in entry.control_codes
    assert "NL" in entry.control_codes

    # Export to PO format
    po_content = block.to_po()
    assert "msgid \"Hero[COLOR:01] wake up[NL]now!\"" in po_content

    # Prepare translation that exceeds original length
    translated_text = "Wahai pahlawan perkasa, bangunlah sekarang juga karena kerajaan sedang dalam bahaya besar!"
    
    # Configure auto-paginator
    paginator = SmartAutoPaginator(
        config=PaginationConfig(
            max_width_px=100,
            max_lines_per_page=2,
            page_break_tag="[PAGE]",
            line_break_tag="[NL]",
            default_char_width_px=6,
        )
    )

    # Inject with pagination and auto-relocation
    free_space = [(0x0800, 0x1000)]
    report = DialogueDissector.inject_translations(
        data=rom,
        block=block,
        translations={0: translated_text},
        encoding="ascii",
        free_space_ranges=free_space,
        schema=schema,
        paginator=paginator,
    )

    assert report.modified_entries == 1
    assert report.relocated_entries == 1
    assert len(report.pointer_updates) == 1

    # Verify updated pointer in ROM
    new_ptr = struct.unpack("<I", rom[table_offset : table_offset + 4])[0]
    assert new_ptr == 0x0800

    # Verify injected content contains PAGE tag byte (0x09) and NL tag byte (0x01)
    injected_bytes = rom[0x0800 : 0x0800 + report.bytes_relocated]
    assert b"\x09" in injected_bytes
    assert b"\x01" in injected_bytes
    assert injected_bytes.endswith(b"\x00")


def test_dialogue_dissector_snes_24bit_pointers():
    rom = bytearray(0x8000)

    # Synthetic SNES LoROM dialogue at 0x1000
    strings = [
        b"Ksatria\x00",
        b"Pedang mistis\x00",
    ]
    str_offsets = [0x1000, 0x1020]
    for s, off in zip(strings, str_offsets):
        rom[off : off + len(s)] = s

    # 3-byte LoROM pointer table at 0x0200 ($80:8000 base -> 24-bit little endian)
    table_offset = 0x0200
    for i, off in enumerate(str_offsets):
        rom[table_offset + i * 3 : table_offset + (i + 1) * 3] = off.to_bytes(3, "little")

    # Extract with 3-byte pointers
    block = DialogueDissector.extract_from_table(
        data=bytes(rom),
        table_offset=table_offset,
        pointer_count=2,
        pointer_size=3,
        endian="<",
        base_address=0,
        encoding="ascii",
        block_id="snes_dialogue",
    )

    assert len(block.entries) == 2
    assert block.entries[0].text == "Ksatria"
    assert block.entries[1].text == "Pedang mistis"

    # Relocate expanded translation to free space
    translations = {0: "Ksatria legendaris dari kerajaan barat"}
    free_space = [(0x2000, 0x3000)]

    report = DialogueDissector.inject_translations(
        data=rom,
        block=block,
        translations=translations,
        encoding="ascii",
        free_space_ranges=free_space,
    )

    assert report.modified_entries == 1
    assert report.relocated_entries == 1

    # Verify 3-byte pointer updated to 0x2000
    new_ptr_bytes = bytes(rom[table_offset : table_offset + 3])
    new_ptr_val = int.from_bytes(new_ptr_bytes, "little")
    assert new_ptr_val == 0x2000


def test_end_to_end_forensic_dialogue_simulation():
    # Build synthetic ROM with Japanese words and Huffman stream
    rom = bytearray(0x8000)

    # 1. Encode Gojuon Japanese text at 0x1000 and 0x1020 with delta 0x40
    base_delta = 0x40
    tata_bytes = bytes([base_delta + HIRAGANA_FULL.index(c) for c in "たたかう"])
    maho_bytes = bytes([base_delta + HIRAGANA_FULL.index(c) for c in "まほう"])
    rom[0x1000 : 0x1000 + len(tata_bytes)] = tata_bytes
    rom[0x1020 : 0x1020 + len(maho_bytes)] = maho_bytes

    # Mine character map directly from ROM
    clusters = JapaneseCharMapMiner.mine_clusters(bytes(rom), mode="1byte", min_consensus_words=2)
    assert len(clusters) > 0
    cluster = clusters[0]
    charmap = cluster.build_charmap()
    assert charmap.decode(tata_bytes) == "たたかう"
    assert charmap.decode(maho_bytes) == "まほう"

    # 2. Huffman compression and bitstream decompression
    corpus = [b"Hero, take this potion and defeat the evil monster.\x00"]
    tree_bytes, compressed_streams = TextCompressionHunter.compress_huffman(corpus, entry_size=2)
    rom[0x2000 : 0x2000 + len(tree_bytes)] = tree_bytes
    rom[0x2200 : 0x2200 + len(compressed_streams[0])] = compressed_streams[0]

    hunter = TextCompressionHunter()
    candidates = hunter.scan_huffman_trees(
        bytes(rom), min_nodes=len(tree_bytes) // 4, confidence_threshold=0.85
    )
    assert len(candidates) > 0
    decomp, bits = candidates[0].decompress_bitstream(bytes(rom), stream_offset=0x2200)
    assert decomp == corpus[0]

    # 3. Tilemap graphic menu label dissection and splicing
    tilemap = Tilemap(width=8, height=4)
    for c in "ITEMPOTION ":
        charmap.add_mapping(bytes([ord(c)]), c)

    for idx, ch in enumerate("ITEM"):
        tilemap.set_entry(1 + idx, 1, TilemapEntry(tile_index=ord(ch), palette_bank=1))

    dissector = TilemapDissector(tilemap, charmap=charmap, min_length=2)
    runs = dissector.scan_text_runs(direction="horizontal")
    assert len(runs) == 1
    assert runs[0].decoded_text == "ITEM"

    ascii_grid = dissector.export_text_grid()
    assert "ITEM" in ascii_grid

    dissector.splice_label(
        row=runs[0].row,
        col=runs[0].col,
        new_text="POTION",
        align="center",
        max_width=6,
    )
    runs_after = dissector.scan_text_runs(direction="horizontal")
    assert runs_after[0].decoded_text == "POTION"
