# MioROM End-to-End Workflow Guide: Game Localization & Reverse Engineering

This guide walks through a complete, real-world game translation and modification pipeline using MioROM. It demonstrates how to progress from an untouched binary ROM image to a fully translated, bit-aligned, and distributable patched game.

---

## The 6-Phase Pipeline Overview

```text
[ Phase 1: Ingestion & Forensics ]
    ├── Unpack container / ROM image (miorom unpack)
    └── Identify encodings and Shannon entropy (miorom inspect)

[ Phase 2: String & Pointer Discovery ]
    ├── Scan text blocks & encoding probe (miorom scan)
    └── Locate primary & secondary pointer tables (PointerScanner)

[ Phase 3: Translation Extraction & Batching ]
    ├── Export strings to CSV / GNU gettext PO (PoHandler)
    └── Split into manageable team batches (miorom split / merge)

[ Phase 4: Typography & Layout Validation ]
    ├── Measure Variable-Width Font (VWF) pixels (PixelWordWrapper)
    └── Validate line wrap and pagination (TextboxSimulator)

[ Phase 5: Dynamic Relocation & Pointer Rebuilding ]
    ├── Construct new string pool (StringPoolBuilder)
    └── Compute 1:1 pointer shifts via LCS alignment (ByteOffsetMapper)

[ Phase 6: Repacking & Patch Distribution ]
    ├── Repack binary filesystem (miorom repack)
    └── Generate verified distribution patch (miorom patch-create)
```

---

## Phase 1: Ingestion & Forensic Analysis

### Step 1.1: Unpack the ROM Container
Start by extracting the target ROM into structured directories:

```bash
miorom unpack "Rune_Factory.nds" "extracted_game/"
```

This generates:
- `sys/`: System executables (`arm9.bin`, `arm7.bin`, overlays).
- `root/`: Full game virtual filesystem.
- `miorom.meta.json`: Container manifest storing FAT boundaries and system settings.

### Step 1.2: Profile Unknown Binaries
If you encounter unknown archive formats or raw binary blobs inside `root/`, inspect them forensically:

```bash
miorom inspect "extracted_game/root/data/script.bin"
```

The inspector reports:
- Shannon block entropy (distinguishes compressed data, code, and raw text).
- Multi-encoding score (ranks ASCII, Shift-JIS, UTF-8, and UTF-16 candidate blocks).
- Suspected pointer table headers or footers.

---

## Phase 2: String & Pointer Table Discovery

### Step 2.1: Scan Text and Discover Pointer Tables
Scan the script binary for text strings and their referencing pointer tables:

```bash
miorom scan "extracted_game/root/data/script.bin" \
    -e shift_jis \
    --min-len 4 \
    --pointers \
    --footer-scan 512 \
    --orphans \
    -o "dialogue_extracted.csv"
```

This command outputs:
- Number of discovered strings.
- Start and end offsets of contiguous text blocks.
- Location, stride, and RAM base address of pointer tables.
- A ready-to-translate CSV file (`dialogue_extracted.csv`).

---

## Phase 3: Translation Management

### Step 3.1: Batching for Translators
For games with tens of thousands of lines, split the master CSV into smaller batch files:

```bash
miorom split dialogue_extracted.csv -o batches/ -s 250 -p rff_
```

Translators fill in the `Translation` column in each batch file.

### Step 3.2: Merging Translated Batches
Merge completed batch files back into a single consolidated master translation:

```bash
miorom merge batches/ -o dialogue_master_translated.csv -m dialogue_extracted.csv
```

### Step 3.3: Integration with Translation Tools (Weblate, Crowdin)
If using translation management systems (TMS), convert strings to GNU gettext PO format using `PoHandler`:

```python
from miorom.text import PoHandler
from miorom.formats.csv_handler import CsvHandler

rows = CsvHandler.import_csv("dialogue_extracted.csv")
po_entries = [
    {"msgid": r.original, "msgstr": r.translation, "context": f"offset_0x{r.offset:06X}"}
    for r in rows
]
PoHandler.export_po(po_entries, "dialogue.po")
```

---

## Phase 4: Typography & Layout Validation

Game text engines usually use Variable-Width Fonts (VWF), where characters vary in width (e.g. `'i'` is 3 pixels, `'M'` is 11 pixels). Measuring text length by character count (`len(text)`) leads to textbox overflow.

### Step 4.1: Measure Dialogue Using True Pixel Metrics

```python
from miorom.platforms.wii import BRFNTFont
from miorom.text import PixelWordWrapper

# Load the game's official font
font = BRFNTFont.from_file("extracted_game/root/font/dialogue.brfnt")

# Configure wrapper with textbox pixel constraints
wrapper = PixelWordWrapper(
    font=font,
    max_pixel_width=240, # Maximum width in pixels per line
    max_lines=3          # Maximum lines per dialogue box
)

# Test a translated string
translated_text = "Good morning! It is a wonderful day to tend to your crops and explore the dungeon."
result = wrapper.wrap(translated_text)

if not result.fits:
    print(f"Warning: Text exceeds textbox! Lines: {len(result.lines)}")
    for line in result.lines:
        print(f"  [{line.pixel_width}px / 240px]: {line.text}")
```

### Step 4.2: Automated Paging for Long Monologues
If translated text exceeds the textbox line limit, use `AutoPaginator` to automatically split it into pages with page-break control tags:

```python
from miorom.text import AutoPaginator

paginator = AutoPaginator(wrapper=wrapper, page_delimiter="<NEXT_PAGE>")
paged_text = paginator.paginate(translated_text)
```

---

## Phase 5: Dynamic Relocation & Pointer Rebuilding

When translated strings are longer than the original Japanese text, the binary expands. Simply overwriting strings in-place corrupts subsequent data.

MioROM provides two methods to solve this:

### Method A: RelocatableBuffer (For Single Script Files)
Maintains an immutable snapshot of original binary data, replacing strings and recalculating all registered pointers in one pass using Longest Common Subsequence (LCS) alignment:

```python
from miorom import RelocatableBuffer

buf = RelocatableBuffer.load("extracted_game/root/data/script.bin")

# Register pointer table locations
# pos: offset of pointer, size: 2 or 4 bytes, endian: "<" or ">"
buf.register_pointer(pos=0x000010, size=4, endian="<")
buf.register_pointer(pos=0x000014, size=4, endian="<")
buf.register_pointer(pos=0x000018, size=4, endian="<")

# Replace dialogue strings
buf.replace_text("おはよう", "Good morning, adventurer!")
buf.replace_text("こんにちは", "Hello there!")

# Automatically shift offsets and recalculate all registered pointers
report = buf.relocate_all()
print(f"Pointers updated: {report.pointers_updated}, Size delta: {report.size_delta} bytes")

buf.save("extracted_game/root/data/script.bin")
```

### Method B: StringPoolBuilder (For Standalone Text Tables)
Builds a fresh contiguous string pool and generates an exact, synchronized pointer table:

```python
from miorom.helper import StringPoolBuilder

builder = StringPoolBuilder(endian="<", alignment=4, null_terminated=True)

# Add all translated dialogue lines in original index order
for row in translated_rows:
    builder.add(row.translation, encoding="utf-8")

# Compile new data blocks
new_pointer_table_bytes = builder.build_pointer_table(base_offset=0x00020000)
new_string_pool_bytes = builder.build_pool()
```

---

## Phase 6: Repacking & Patch Distribution

### Step 6.1: Repack the ROM
Repack the modified directory tree back into a bootable ROM image. MioROM rebuilds the filesystem table and fixes hardware checksums automatically:

```bash
miorom repack "extracted_game/" "Rune_Factory_Translated.nds"
```

### Step 6.2: Create a Legal Distribution Patch
Never distribute full copyrighted ROM files. Generate a BPS or Xdelta patch comparing the clean original ROM against the translated ROM:

```bash
# For cartridge ROMs (NDS, GBA, SNES, N64):
miorom patch-create "clean.nds" "Rune_Factory_Translated.nds" -o "RF_Indo_v1.0.bps" -f bps

# For large optical disc images (Wii, GameCube, PS1 ISO):
miorom patch-create "clean.iso" "translated.iso" -o "RF_Indo_v1.0.xdelta" -f xdelta
```

### Step 6.3: End-User Application
End users apply the patch to their legally dumped game image:

```bash
miorom patch-apply "clean.nds" "RF_Indo_v1.0.bps" -o "game_patched.nds"
```
