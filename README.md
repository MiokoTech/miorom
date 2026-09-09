# MioROM

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests: 468 Passed](https://img.shields.io/badge/Tests-468%20Passed-brightgreen.svg)](tests/)
[![Platforms: Multi-Console](https://img.shields.io/badge/Platforms-NDS%20%7C%20Wii%20%7C%20GC%20%7C%20N64%20%7C%20GBA%20%7C%20SNES%20%7C%20PS1-orange.svg)](docs/API_REFERENCE.md)

**MioROM** is an advanced, modular Python framework and low-level primitive library for ROM hacking, game localization engineering, and binary reverse engineering.

Designed with a **library-first philosophy** (analogous to `ndspy` and `pwntools`), MioROM provides foundational building blocks, platform container parsers, instruction scanners, and pointer recalculation engines required to build reliable, reproducible game extraction, translation, and repacking pipelines in pure Python.

---

## Documentation

- [API Reference and Architecture Guide](docs/API_REFERENCE.md) - Comprehensive index of all subpackages and 60+ core classes.
- [Binary and Assembly Primitives Guide](docs/BINARY_PRIMITIVES.md) - Technical guide for low-level patching, micro-assembly, struct serialization, and symbol mapping.
- [Command-Line Interface (CLI) Reference](docs/CLI_REFERENCE.md) - Complete manual for `miorom` terminal tools (`unpack`, `repack`, `inspect`, `scan`, etc.).
- [Console Platform & Format Reference](docs/PLATFORMS.md) - Deep dive into NDS, Wii/GC, PS1, N64, GBA, SNES, and Mega Drive formats.
- [End-to-End Localization Workflow Guide](docs/WORKFLOW_GUIDE.md) - 6-phase walkthrough from untouched ROM to distributed patch.
- [Adding New Platforms (Plugin Guide)](docs/PLUGIN_GUIDE.md) - Registering custom `BaseRomHandler` implementations without forking MioROM.
- [Library Contracts](docs/LIBRARY_CONTRACTS.md) - Serialization, streaming, structured exceptions, patch composition, pipeline extension, and structural-typing contracts.
- [Security Guide](docs/SECURITY.md) - Path traversal / zip-slip protection and the checklist for safely extracting untrusted archives.

---

## Installation

### From GitHub

Install using `pip`:

```bash
pip install miorom
```

### From Source (Development Mode)

```bash
git clone https://github.com/MiokoTech/miorom.git
cd miorom
pip install -e .
```

To run the verification test suite:

```bash
pytest
```

---

## Platform Support Matrix

MioROM provides native parsers, serializers, and filesystem handlers across multiple retro and modern console architectures without external binary dependencies:

| Platform | Containers & Filesystems | Executables & Formats | Text, Fonts & Compression |
| :--- | :--- | :--- | :--- |
| **Nintendo DS** | `.nds` ROM, NARC (`.narc`) archives, FAT | ARM9/ARM7 binaries, overlays | NFTR fonts, SDAT audio, LZ10, LZ11, RLE |
| **Nintendo Wii / GameCube** | Optical Disc (`.iso`, `.gcm`), U8 (`.arc`, `.szs`), FST | DOL executables, ELF objects | BRFNT fonts, TPL textures, Yaz0 |
| **Game Boy Advance** | `.gba` ROM, Cartridge headers | ARM/Thumb relative branches | BGR555 palettes, 4bpp tiles, Complement CRC |
| **Nintendo 64** | `.z64` (BE), `.v64` (Swapped), `.n64` (LE) | MIPS split-pointer scanner | IPL3 CIC checksum verification (all variants) |
| **Super Nintendo** | `.sfc`, `.smc` (LoROM / HiROM / ExHiROM) | 65816 memory mapping | 2bpp/4bpp planar tiles, 16-bit complement CRC |
| **PlayStation 1** | Optical Disc (ISO9660, CUE/BIN multi-track) | PS-X EXE, STR video, CD-XA audio | TIM textures, MDEC video bitstreams, EDC/ECC |
| **Sega Genesis / Mega Drive** | `.md`, `.bin`, `.smd` (Interleaved de-interleaving) | 68000 header & SRAM registers | 16-bit big-endian ROM checksum recalculation |

---

## Core Pillars & Capabilities

### 1. Low-Level Binary Manipulation & Patching
- **`BinaryReader` & `BinaryWriter`**: High-performance stream I/O with dynamic endianness switching (`<` / `>`), temporary context seeking (`with reader.at(offset): ...`), and boundary alignment padding.
- **`PatchWriter`**: Fluent binary patch emitter with automatic cursor tracking, range replacements, and instant IPS distribution patch generation.
- **`RecordBuilder`**: Fluent struct writer constructing binary headers and packed records with fixed-width strings, Pascal strings, and memory alignment without brittle format strings.
- **`RelocatableBuffer`**: Immutable pristine snapshot buffer preventing offset drift across chained text edits, recalculating all registered pointers in a single pass.
- **`HexDiffHighlighter`**: Terminal verification tool rendering colorized ANSI hex diffs (green for additions, red for original bytes) before writing changes to disk.
- **`SymbolMap`**: Memory and ROM address annotator with export to No$GBA (`.sym`), Dolphin (`.map`), and Ghidra CSV labels.

### 2. Disassembly, Assembly & Static Analysis
- **`UniversalDisassembler`**: Multi-architecture disassembler supporting PowerPC, ARM32, Thumb-16, and MIPS without native C dependencies.
- **`AsmSnippet`**: Pure-Python micro-assembler for compiling small ARM32 and MIPS instruction sequences (branches, loads, calls, returns) without external toolchains.
- **`PPCInstructionScanner` & `MIPSInstructionScanner`**: Searches binary executables for split-pointer load pairs (`lis` + `addi` / `lui` + `addiu`) and patches them in-place.
- **`CodeCaveFinder` & `TrampolineHook`**: Locates contiguous unused padding bytes (`0x00`/`0xFF`) and constructs 5-instruction trampolines preserving original opcodes.
- **`AntiPiracyBypasser`**: Scans and applies surgical patches to NDS cartridge checks, checksum verification loops, and PowerPC integrity branches.

### 3. Pointer Tables & Relocation Engines
- **`PointerTable` & `PointerEntry`**: Manages absolute, relative, segmented, and flagged pointers (`offset + flags`) with 1:1 relocation.
- **`MultiLevelPointerTable`**: Resolves cascading multi-tier pointer hierarchies (Chapter -> Scene -> Text Block).
- **`ByteOffsetMapper`**: Computes exact 1:1 address relocation using Longest Common Subsequence (LCS) alignment when text data expands.
- **`FarPointerRelocator` & `RomLayoutExpander`**: Relocates binary assets into expanded ROM memory banks (GBA 32MB, N64 64MB) with automatic hardware checksum repairs.

### 4. Text, Typography & Localization Engineering
- **`PixelWordWrapper` & `FontMetrics`**: Measures dialogue lines against true on-screen pixel boundaries for Variable-Width Fonts (VWF), preventing textbox overflows.
- **`TrieTranscoder`**: High-performance greedy longest-prefix transcoder for Dual-Tile Encoding (DTE), Byte-Pair Encoding (BPE), and custom `.tbl` character tables.
- **`GameTextTemplate`**: Bidirectional dialogue template engine with dynamic control tags and reverse parameter extraction.
- **`StringAligner`**: Correlates and transfers translated strings between regional releases (e.g. Japanese v1.0 to USA v1.1) despite shifted or inserted rows.
- **`PoHandler`**: Two-way bridge connecting game text to GNU gettext PO files for standard translation toolchains (Weblate, Crowdin, Poedit).

### 5. Filesystem, Containers & Disc Images
- **`RomManager`**: Unified auto-detecting ROM unpacker and repacker for NDS, GameCube/Wii ISO, U8 Archive, NARC, ISO9660, and Cartridges.
- **`ISO9660` & `CueBinDisc`**: Pure-Python optical disc filesystem parser and injector with LBA sector reallocation and ECMA-130 EDC/ECC recalculation.
- **`VirtualFileSystem` (VFS)**: In-memory hierarchical filesystem layer allowing transparent archive mounting, file browsing, and in-place node editing.
- **`FstInjector`**: In-place GameCube and Wii File System Table modifier without external tools like `wit` or `gcit`.

### 6. Compression, Audio & Graphics Codecs
- **Nintendo BIOS Compression**: LZ10 (0x10), LZ11 (0x11), RLE (0x30), and Huffman 4/8-bit (0x24, 0x28).
- **Nintendo Yaz0**: Ubiquitous compression across N64, GameCube, Wii, and Switch.
- **Tile Graphics Engine**: 1bpp, 2bpp (GB/NES), 4bpp chunky/planar (SNES/GBA/NDS), and 8bpp codecs with `TileReducer` deduplication.
- **Pillow / PNG Bridge (`ImageBridge`)**: Two-way converter between game tilemaps/palettes and standard PNG images.
- **Audio & Video**: PlayStation CD-XA ADPCM decoder, Nintendo DS SDAT sound container, and PS1 MDEC / STR movie demuxer.

---

## Quickstart Guide

### 1. Universal ROM Unpack and Repack

MioROM automatically detects container and ROM formats from magic headers, unpacks system binaries to `sys/` and assets to `root/`, and repacks with hardware checksum fixes:

```python
from miorom import unpack_rom, repack_rom

# Unpack any supported ROM (NDS, ISO, NARC, U8 ARC, Cartridge)
meta = unpack_rom("game.nds", "unpacked/")
print(f"Format: {meta['format']}, Files: {meta.get('file_count')}")

# Modify assets in unpacked/root/ or binaries in unpacked/sys/...

# Repack cleanly into a compliant, bootable ROM
repack_rom("unpacked/", "game_patched.nds")
```

### 2. Surgical Binary Patching with `PatchWriter` and `HexDiffHighlighter`

Apply precise in-memory modifications, verify the binary changes visually, and export standard distribution patches:

```python
from miorom.patch import PatchWriter
from miorom.core import HexDiffHighlighter

rom_data = open("arm9.bin", "rb").read()
writer = PatchWriter(rom_data)

# Apply contiguous writes and pointer updates
writer.write_at(0x00014000, b"TRANSLATED_TEXT\x00")
writer.write_u32_at(0x00010004, 0x02014000, endian="<")

patched_data = writer.apply()

# Visually verify modified bytes in terminal
HexDiffHighlighter.print_diff(
    original=rom_data,
    modified=patched_data,
    offset=0x00010000,
    size=32,
    use_color=True,
)

# Export as an IPS distribution patch
with open("patch.ips", "wb") as f:
    f.write(writer.build_ips())
```

### 3. Assembling Micro-Assembly Routines with `AsmSnippet`

Emit standalone ARM32 or MIPS routines without requiring external cross-compiler toolchains:

```python
from miorom.asm import AsmSnippet

# Assemble an ARM32 hook routine
arm = AsmSnippet.arm("<")
arm.push(["r4", "r5", "lr"])
arm.mov_imm("r0", 42)
arm.add_imm("r1", "r0", 10)
arm.bx("lr")
machine_code = arm.emit()

# Output: 20 bytes of ARM32 machine code ready for code cave injection
```

### 4. Serializing Structs and Records with `RecordBuilder`

Construct binary table records, fixed-width entries, and headers cleanly:

```python
from miorom.core import RecordBuilder

entry = (
    RecordBuilder(endian="<")
    .u32(0x1001)                                         # Item ID
    .fixed_str("Elixir", length=16, pad_byte=0x00)       # Fixed-length string
    .pascal_str("Fully restores HP/MP", length_size=1)   # Pascal string
    .u16(999)                                            # Price
    .align(4)                                            # Word alignment
    .build()
)
```

### 5. String Relocation and Pointer Recalculation

Safely expand game dialogue strings while recalculating internal pointer tables via LCS alignment:

```python
from miorom import RelocatableBuffer

# Load a script segment
buf = RelocatableBuffer.load("dialogue.bin")

# Register pointer offsets and dynamic size headers
buf.register_anchored_field(pos=0x00, size=2, anchor_type="size_delta")
buf.register_pointer(pos=0x04, size=2, endian="<")
buf.register_pointer(pos=0x06, size=2, endian="<")

# Perform chained text replacements safely
buf.replace_text("Hello", "Good morning, adventurer!")
buf.replace_text("Item found.", "You have obtained a rare treasure!")

# Recalculate all registered pointers in one pass
report = buf.relocate_all()
buf.save("dialogue_expanded.bin")
```

### 6. Variable-Width Font (VWF) Word Wrapping

Validate and wrap dialogue lines using exact on-screen pixel metrics instead of naive character counts:

```python
from miorom.text import BitmapFont, PixelWordWrapper

# Initialize font with proportional glyph metrics
font = BitmapFont(default_height=12, default_advance=8)
font.set_character_advance("i", 3)
font.set_character_advance("W", 12)

wrapper = PixelWordWrapper(font=font, max_pixel_width=220, max_lines=3)
result = wrapper.wrap("Welcome to the kingdom of Norad! We hope your journey was pleasant.")

print(f"Total lines: {len(result.lines)}, Fits in textbox: {result.fits}")
for line in result.lines:
    print(f"Line ({line.pixel_width}px): {line.text}")
```

---

## Architecture and Source Layout

```text
miorom/
├── pyproject.toml              # Build system and dependency specifications
├── README.md                   # Project overview and quickstart
├── docs/
│   ├── API_REFERENCE.md        # Comprehensive 60+ class API reference
│   ├── BINARY_PRIMITIVES.md    # Low-level primitives developer guide
│   ├── CLI_REFERENCE.md        # Terminal command manual
│   ├── PLATFORMS.md            # Per-console format specifications
│   ├── WORKFLOW_GUIDE.md       # 6-phase localization pipeline walkthrough
│   ├── PLUGIN_GUIDE.md         # Custom BaseRomHandler registration guide
│   ├── LIBRARY_CONTRACTS.md    # Serialization, streaming, extensibility contracts
│   └── SECURITY.md             # Untrusted-archive extraction safety guide
├── src/miorom/
│   ├── core/                   # Stream I/O, Structs, Relocation, SymbolMap, HexDiff
│   ├── patch/                  # IPS, BPS, Xdelta, and PatchWriter
│   ├── asm/                    # Universal disassembler, AsmSnippet, Hooks, Anti-piracy
│   ├── script/                 # ScriptVM, AST decompiler, IR lifter, Repackers
│   ├── text/                   # VWF wrapper, CharMap, DTE, PO handler, Aligner
│   ├── platforms/              # NDS, Wii/GC, N64, GBA, GB, SNES, PSX, MD, ISO9660, CD-ROM
│   ├── graphics/               # Tile codecs (1-8bpp), Palettes, TileReducer, ImageBridge
│   ├── compression/            # LZ10, LZ11, RLE, Yaz0, Huffman, Heuristic LZSS
│   ├── audio/                  # SDAT, IMA-ADPCM, CD-XA audio decoders and WAV builders
│   ├── save/                   # Checksum calculators (CRC16/32, Fletcher) and DualSlotSave
│   ├── archive/                # Container unpackers and in-memory VirtualFileSystem (VFS)
│   ├── link/                   # In-ROM ELF32 object linker and cave injector
│   ├── rom/                    # Universal ROM unpacker and repacker manager
│   ├── scanner/                # Deep signature inspector, entropy profiling, crypto scans
│   └── cli/                    # Command-line interface commands
└── tests/                      # Pytest verification suite (405 unit tests)
```

---

## Contributing & Testing

Contributions are welcome. Please ensure that all changes include comprehensive unit tests and pass the entire test suite:

```bash
# Run all unit tests
pytest

# Run tests with coverage reporting
pytest --cov=miorom tests/
```

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
