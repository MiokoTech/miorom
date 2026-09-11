# MioROM

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests: 547 Passed](https://img.shields.io/badge/Tests-547%20Passed-brightgreen.svg)](tests/)
[![Documentation](https://img.shields.io/badge/docs-miokotech.github.io%2Fmiorom-06b6d4.svg?style=flat&logo=materialformkdocs&logoColor=white)](MioROM Documentations)
[![Platforms: Multi-Console](https://img.shields.io/badge/Platforms-NDS%20%7C%20Wii%20%7C%20GC%20%7C%20N64%20%7C%20GBA%20%7C%20SNES%20%7C%20NES%20%7C%20PS1-orange.svg)](https://miokotech.github.io/miorom/PLATFORMS/)

**MioROM** is an advanced, modular Python framework and low-level primitive library for ROM hacking, game localization engineering, and binary reverse engineering.

Designed with a **library-first philosophy** (analogous to `ndspy` and `pwntools`), MioROM provides foundational building blocks, platform container parsers, instruction scanners, and pointer recalculation engines required to build reliable, reproducible game extraction, translation, and repacking pipelines in pure Python.

---

## Documentation

Full online documentation is deployed and accessible at **[Read more here](https://miokotech.github.io/miorom/)**.

- [API Reference and Architecture Guide](https://miokotech.github.io/miorom/API_REFERENCE/) - Comprehensive index of all subpackages and 70+ core classes.
- [Binary and Assembly Primitives Guide](https://miokotech.github.io/miorom/BINARY_PRIMITIVES/) - Technical guide for low-level patching, micro-assembly, struct serialization, and symbol mapping.
- [Command-Line Interface (CLI) Reference](https://miokotech.github.io/miorom/CLI_REFERENCE/) - Complete manual for `miorom` terminal tools (`unpack`, `repack`, `inspect`, `scan`, etc.).
- [Console Platform & Format Reference](https://miokotech.github.io/miorom/PLATFORMS/) - Deep dive into NDS, Wii/GC, PS1, N64, GBA, SNES, NES, and Mega Drive formats.
- [End-to-End Localization Workflow Guide](https://miokotech.github.io/miorom/WORKFLOW_GUIDE/) - 6-phase walkthrough from untouched ROM to distributed patch.
- [Cookbook & Golden Pipelines](https://miokotech.github.io/miorom/COOKBOOK/) - 10 end-to-end production pipelines (NDS, GBA, SNES, N64, GC, PS1, Sega, and PC-Engine recipes).
- [Adding New Platforms (Plugin Guide)](https://miokotech.github.io/miorom/PLUGIN_GUIDE/) - Registering custom console handlers and codecs via inheritance or entry_points.
- [Library Contracts](https://miokotech.github.io/miorom/LIBRARY_CONTRACTS/) - Serialization, streaming, structured exceptions, patch composition, pipeline extension, and structural-typing contracts.
- [Security Guide](https://miokotech.github.io/miorom/SECURITY/) - Path traversal / zip-slip protection and the checklist for safely extracting untrusted archives.
- [Release Changelog](https://miokotech.github.io/miorom/CHANGELOG/) - Version history, release notes, and migration guidelines.

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
| **Nintendo DS** | `.nds` ROM, NARC (`.narc`) archives, FAT | ARM9/ARM7 binaries, overlays, Thumb-16 | NFTR fonts, NCLR/NCGR/NSCR graphics, SDAT audio, LZ10, LZ11, RLE |
| **Nintendo Wii / GameCube** | Optical Disc (`.iso`, `.gcm`), U8 (`.arc`, `.szs`), FST | DOL executables, ELF objects, PPC32 | BRFNT fonts, TPL textures, DSP-ADPCM audio, Yaz0, Yay0 |
| **Game Boy Advance** | `.gba` ROM, Cartridge headers | ARM/Thumb relative branches, ThumbSnippet | BGR555 palettes, 4bpp tiles, Complement CRC, aPLib |
| **Nintendo 64** | `.z64` (BE), `.v64` (Swapped), `.n64` (LE) | MIPS split-pointer scanner, COP1 floats | IPL3 CIC checksums, Fast3D textures, Yay0, Yaz0 |
| **Super Nintendo** | `.sfc`, `.smc` (LoROM / HiROM / ExHiROM) | 65816 memory mapping & REP/SEP tracking | 2bpp/4bpp planar tiles, SPC700 BRR audio, SnesSnippet |
| **Nintendo Entertainment System** | `.nes`, `.unf` (iNES, NES 2.0) | MOS 6502 disasm & prologue scan | Mapper detection (MMC1/3/5, UNROM, etc.), PRG/CHR separation, 2bpp tiles |
| **PlayStation 1** | Optical Disc (ISO9660, CUE/BIN multi-track) | PS-X EXE, STR video, CD-XA audio | TIM textures, SPU-ADPCM VAG audio, MDEC video bitstreams, EDC/ECC |
| **Sega Genesis / Mega Drive** | `.md`, `.bin`, `.smd` (Interleaved de-interleaving) | 68000 header & SRAM registers | 16-bit big-endian ROM checksum recalculation, M68K disasm |

---

## Core Pillars & Capabilities

### 1. Low-Level Binary Manipulation & Patching
- **`BinaryReader` & `BinaryWriter`**: High-performance stream I/O with dynamic endianness switching (`<` / `>`), temporary context seeking (`with reader.at(offset): ...`), and boundary alignment padding.
- **Patch Formats**: Native creators and appliers for **IPS**, **BPS** (CRC32 verified), **UPS** (XOR diffing with VLQ encoding), and **XDelta** (VCDIFF).
- **`BinaryStruct`**: Declarative binary serialization and parsing system with typed fields (`U8`, `U16`, `U32`, `Float32`, `FixedString`, `Bitfield`, `PascalString`).
- **`CStructOverlay` & `CStructInstance`**: Interactive ANSI C struct parser compiling C declarations directly into binary layouts with attribute/dict access, table iteration, and in-place binary writes.
- **`RecordBuilder`**: Fluent struct writer constructing binary headers and packed records with fixed-width strings, Pascal strings, and memory alignment without brittle format strings.
- **`RelocatableBuffer`**: Immutable pristine snapshot buffer preventing offset drift across chained text edits, recalculating all registered pointers in a single pass.
- **`HexDiffHighlighter`**: Terminal verification tool rendering colorized ANSI hex diffs (green for additions, red for original bytes) before writing changes to disk.
- **`SymbolMap`**: Memory and ROM address annotator with export to No$GBA (`.sym`), Dolphin (`.map`), and Ghidra CSV labels.

### 2. Disassembly, Assembly & Static Analysis
- **`UniversalDisassembler`**: Multi-architecture disassembler supporting 8 architectures: **ARM32**, **Thumb-16**, **PowerPC**, **MIPS I-IV / COP1**, **Game Boy (SM83)**, **Motorola 68000**, **MOS 6502 (NES)**, and **W65C816 (SNES with dynamic REP/SEP tracking)** without native C dependencies.
- **`SymbolicXrefEngine` & `XRefDatabase`**: Multi-architecture symbolic cross-reference discovery (ARM, Thumb, PowerPC, MIPS, W65C816, MOS 6502) and call graph builder with IDA/Ghidra style `; CODE XREF:` and `; DATA XREF:` disassembly annotations.
- **`AsmSnippet`**: Fluent pure-Python micro-assembler for compiling instruction sequences without external toolchains:
  - `AsmSnippet.arm()` (ARM32)
  - `AsmSnippet.thumb()` (16-bit Thumb for GBA / NDS)
  - `AsmSnippet.mips()` (MIPS32 for PS1 / N64 / PSP)
  - `AsmSnippet.ppc()` (PowerPC 32-bit for GameCube / Wii)
  - `AsmSnippet.sm83()` (Game Boy)
  - `AsmSnippet.snes()` (W65C816 for SNES)
- **`PPCInstructionScanner` & `MIPSInstructionScanner`**: Searches binary executables for split-pointer load pairs (`lis` + `addi` / `lui` + `addiu`) and patches them in-place.
- **`CodeCaveFinder` & `TrampolineHook`**: Locates contiguous unused padding bytes (`0x00`/`0xFF`) and constructs multi-architecture trampolines preserving original opcodes.
- **`AntiPiracyBypasser`**: Scans and applies surgical patches to NDS cartridge checks, checksum verification loops, and PowerPC integrity branches.

### 3. Pointer Tables & Relocation Engines
- **`PointerTable` & `PointerEntry`**: Manages absolute, relative, segmented, and flagged pointers (`offset + flags`) with 1:1 relocation.
- **`MultiLevelPointerTable`**: Resolves cascading multi-tier pointer hierarchies (Chapter -> Scene -> Text Block).
- **`ByteOffsetMapper`**: Computes exact 1:1 address relocation using Longest Common Subsequence (LCS) alignment when text data expands.
- **`FarPointerRelocator` & `RomLayoutExpander`**: Relocates binary assets into expanded ROM memory banks (GBA 32MB, N64 64MB) with automatic hardware checksum repairs.

### 4. Text, Typography & Localization Engineering
- **`PixelWordWrapper` & `FontMetrics`**: Measures dialogue lines against true on-screen pixel boundaries for Variable-Width Fonts (VWF), preventing textbox overflows.
- **`BMFont` & `PNGCodec`**: AngelCode BMFont reader/writer (Text & XML formats), automatic glyph atlas texture packing, and built-in pure-Python PNG encoder/decoder without external dependencies.
- **`TrieTranscoder`**: High-performance greedy longest-prefix transcoder for Dual-Tile Encoding (DTE), Byte-Pair Encoding (BPE), and custom `.tbl` character tables.
- **`GameTextTemplate`**: Bidirectional dialogue template engine with dynamic control tags and reverse parameter extraction.
- **`StringAligner`**: Correlates and transfers translated strings between regional releases (e.g. Japanese v1.0 to USA v1.1) despite shifted or inserted rows.
- **`PoHandler`**: Two-way bridge connecting game text to GNU gettext PO files for standard translation toolchains (Weblate, Crowdin, Poedit).

### 5. Fan Translation Reverse Engineering Toolkit
- **`JapaneseCharMapMiner`**: Gojūon relative search engine that discovers game-specific Japanese encodings by mining hiragana/katakana character rows with dakuten variants; auto-generates draft `.tbl` files without prior encoding knowledge.
- **`FontDissector`**: Heuristic font bank scanner combining entropy scoring, stroke density analysis, and glyph diversity checks; locates adjacent VWF width tables, exports PNG spritesheets, and round-trips glyph and width data back into ROM buffers.
- **`TextCompressionHunter`**: Forensic scanner discovering embedded Huffman trees via root-0 graph traversal (no fixed node count required), DTE bigram tables, and produces optimal re-compressed bitstreams for translated text.
- **`ScriptVMDissector`**: Linear sweep bytecode disassembler for arbitrary opcode schemas with full handling of TEXT, BRANCH_REL, BRANCH_ABS, SWITCH, CONTROL, and TERMINATOR categories; `splice_and_relink()` rewrites translated strings and automatically recalculates all branch deltas, absolute jump targets, and switch tables in-place.
- **`TilemapDissector`**: Menu nametable RE suite — scans horizontal/vertical graphic text runs, renders ASCII grid layouts, splices translated labels with left/center/right alignment and boundary guards, exports/imports JSON layout files for pipeline integration, and applies batch translations in a single pass.
- **`VWFHookEngine`**: End-to-end VWF hook deployer — verifies hook site byte integrity, synthesizes architecture-specific width lookup routines (ARM32, Thumb, MIPS32, SNES W65C816, MOS 6502), allocates code caves automatically, and atomically patches ROM buffers with simulate mode for safe preflight validation.

### 6. Filesystem, Containers & Disc Images
- **`RomManager`**: Unified auto-detecting ROM unpacker and repacker for NDS, GameCube/Wii ISO, U8 Archive, NARC, NES, ISO9660, and Cartridges.
- **`NESRom` & `NESHeaderStruct`**: iNES and NES 2.0 container parser with mapper identification (MMC1/3/5, UNROM, etc.), PRG/CHR separation, and 512-byte trainer handling.
- **`ISO9660` & `CueBinDisc`**: Pure-Python optical disc filesystem parser and injector with LBA sector reallocation and ECMA-130 EDC/ECC recalculation.
- **`VirtualFileSystem` (VFS)**: In-memory hierarchical filesystem layer allowing transparent archive mounting, file browsing, and in-place node editing.
- **`FstInjector`**: In-place GameCube and Wii File System Table modifier without external tools like `wit` or `gcit`.

### 7. Compression, Audio & Graphics Codecs
- **Compression Codecs**:
  - **Nintendo BIOS**: LZ10 (0x10), LZ11 (0x11), RLE (0x30), and Huffman 4/8-bit (0x24, 0x28).
  - **Nintendo Yaz0 & Yay0**: Standard Yaz0 and N64/GC Yay0 3-stream LZSS.
  - **aPLib**: High-ratio pure-Python decompressor and compressor supporting raw streams and AP32 containers.
- **Audio Codecs & Exporters**:
  - **Sony PS1/PS2 VAG (`VAGFile`, `VAGCodec`)**: SPU-ADPCM 16-byte block parser, encoder, decoder, and direct WAV exporter.
  - **SNES SPC700 BRR (`BRRCodec`)**: 9-byte BRR block encoder/decoder with S-DSP 4-filter interpolation and WAV generation.
  - **Nintendo GameCube / Wii DSP-ADPCM (`DSPADPCMCodec`)**: 8-byte frame audio decoder and WAV converter.
  - **PlayStation CD-XA**: `CdXaDecoder` ADPCM sector decoder and WAV exporter.
  - **Nintendo DS SDAT & SSEQ**: `SDATContainer` and `SSEQSequence` parser.
- **Graphics Suite**:
  - **Nintendo DS 2D Engine**: `NCLRFile` (palettes), `NCGRFile` (character graphics), and `NSCRFile` (screen map layouts).
  - **Tile Graphics**: 1bpp, 2bpp (GB/NES), 4bpp chunky/planar (SNES/GBA/NDS), and 8bpp codecs with `TileReducer` deduplication.
  - **Pillow / PNG Bridge (`ImageBridge`)**: Two-way converter between game tilemaps/palettes and standard PNG images.
  - **PlayStation Video**: PS1 MDEC / STR movie stream demuxer.

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
├── CHANGELOG.md                # Version history and release notes
├── docs/
│   ├── API_REFERENCE.md        # Comprehensive 70+ class API reference (updated v1.0.0)
│   ├── BINARY_PRIMITIVES.md    # Low-level primitives developer guide
│   ├── CLI_REFERENCE.md        # Terminal command manual
│   ├── COOKBOOK.md             # 10 end-to-end golden pipelines and recipes
│   ├── PLATFORMS.md            # Per-console format specifications
│   ├── WORKFLOW_GUIDE.md       # 6-phase localization pipeline walkthrough
│   ├── PLUGIN_GUIDE.md         # Custom BaseRomHandler registration guide
│   ├── LIBRARY_CONTRACTS.md    # Serialization, streaming, extensibility contracts
│   └── SECURITY.md             # Untrusted-archive extraction safety guide
├── src/miorom/
│   ├── core/                   # Stream I/O, Structs, Relocation, SymbolMap, HexDiff
│   ├── patch/                  # IPS, BPS, UPS, PPF, XDelta, PatchWriter, CheatCode
│   ├── asm/                    # Universal disassembler, AsmSnippet, Hooks, VWFHookEngine ← new
│   ├── script/                 # ScriptVM, ScriptVMDissector, AST decompiler, IR lifter ← new
│   ├── text/                   # VWF wrapper, CharMap, JapaneseCharMapMiner, DTE, PO  ← new
│   ├── platforms/              # NDS, Wii/GC, N64, GBA, GB, SNES, PSX, MD, ISO9660, CD-ROM
│   ├── graphics/               # Tile codecs, FontDissector, TilemapDissector          ← new
│   ├── compression/            # LZ10, LZ11, RLE, Yaz0, Huffman, TextCompressionHunter ← new
│   ├── audio/                  # SDAT, IMA-ADPCM, CD-XA audio decoders and WAV builders
│   ├── save/                   # Checksum calculators (CRC16/32, Fletcher) and DualSlotSave
│   ├── archive/                # Container unpackers and in-memory VirtualFileSystem (VFS)
│   ├── link/                   # In-ROM ELF32 object linker and cave injector
│   ├── rom/                    # Universal ROM unpacker and repacker manager
│   ├── scanner/                # Deep signature inspector, entropy profiling, crypto scans
│   └── cli/                    # Command-line interface commands
└── tests/                      # Pytest verification suite (380 passed)
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

## References

Technical documentation, hardware specifications, and prior-art resources consulted during the development of MioROM:

### Hardware & Format Specifications
- [GBATEK — GBA/NDS/DSi Technical Reference](https://problemkaputt.de/gbatek.htm) — Martin Korth. ARM9/ARM7 memory maps, NDS ROM format, VRAM layout, SDAT audio pipeline, graphics engine.
- [no$gba Documentation](https://problemkaputt.de/gba.htm) — GBA cartridge header, CPU timing, DMA, interrupt controller.
- [SNESdev Wiki](https://snes.nesdev.org/wiki/SNESdev_Wiki) — SNES memory mapping (LoROM/HiROM/ExHiROM), 65816 addressing, PPU registers, SPC700.
- [NESDev Wiki](https://www.nesdev.org/wiki/Nesdev_Wiki) — NES/Famicom iNES/NES 2.0 cartridge format, mapper table, 6502 opcode reference, PPU tile encoding.
- [Sega Mega Drive / Genesis Technical Overview](https://wiki.megadrive.org/index.php?title=Technical_Overview) — VDP register set, 68000 vector table, M68K bus timing, CRAM palette format.
- [MIPS Architecture Reference Manual, Vol. I-II](https://www.mips.com/products/architectures/) — R3000 / R4300i ISA, COP1 floating-point, delay slot behavior (PS1, N64).
- [PowerPC Microprocessor Family: The Programming Environments](https://www.nxp.com/) — PPC 32-bit instruction set (GameCube/Wii Broadway/Gekko).
- [ARM Architecture Reference Manual (ARMv4T/ARMv5TE)](https://developer.arm.com/documentation/) — ARM32 and Thumb-16 ISA, BL/BX encoding, pipeline compensation (GBA/NDS ARM7/ARM9).
- [Motorola 68000 Programmer's Reference Manual](https://www.nxp.com/docs/en/reference-manual/M68000PRM.pdf) — M68K opcode encoding, effective address modes, BRA/BSR displacement.

### Console ROM & Disc Format Documentation
- [NDSPY Documentation](https://ndspy.readthedocs.io/) — Nintendo DS ROM structure, NARC filesystem, FAT/FNT layout, ARM9/ARM7 overlay tables.
- [Caitsith2's NARC Specification](http://problemkaputt.de/gbatek.htm#dsfilesystem) — NDS archive container spec.
- [Nintendo GameCube / Wii GCM/ISO Filesystem](https://wiibrew.org/wiki/Wii_disc) — DOL executable sections, FST table layout, Appldr format.
- [ISO 9660 / ECMA-119 Standard](https://www.ecma-international.org/publications-and-standards/standards/ecma-119/) — Optical disc filesystem structure.
- [Sony PlayStation Executable Format (PS-X EXE)](https://psx-spx.consoledev.net/) — Martin Korth's PSX/PS2 hardware reference. SPU-ADPCM, CD-XA, TIM texture.
- [CSO Compressed ISO Format Specification](https://www.romhacking.net/utilities/631/) — PSP sector-level CISO compression.
- [UPS Patch Format Specification](https://www.romhacking.net/documents/392/) — XOR diffing, VLQ encoding, CRC32 layout.
- [BPS Patch Format Specification](https://www.romhacking.net/documents/746/) — Delta patching with source/target copy blocks.
- [PPF 3.0 Patch Format Specification](https://www.romhacking.net/utilities/353/) — PlayStation disc patch format, undo data, sector validation.

### Compression Algorithm References
- [Haruhiko Okumura — LZSS Data Compression (1989)](https://oku.edu.mie-u.ac.jp/~okumura/compression/) — Original 4096-byte sliding window LZSS algorithm.
- [aPLib Compression Library](https://ibsensoftware.com/products_aPLib.html) — Jorgen Ibsen. High-ratio LZ algorithm and AP32 container format.
- [Nintendo Yaz0 Compression](https://wiki.tockdom.com/wiki/Yaz0_(File_Format)) — Wii/GC LZSS variant with 8-bit group flags.
- [Nintendo Yay0 Compression](https://wiki.tockdom.com/wiki/Yay0_(File_Format)) — N64/GC 3-stream LZSS decompressor.
- [Electronic Arts RefPack / QFS](https://www.wiki.sc4devotion.com/index.php?title=DBPF_Compression) — EA's 2-4 byte match LZ codec.
- [RFC 1951 — DEFLATE Compressed Data Format](https://www.rfc-editor.org/rfc/rfc1951) — Canonical Huffman tree and LZ77 back-reference encoding.

### Audio Format References
- [SPC700 / S-DSP BRR Audio Format](https://wiki.superfamicom.org/spc700-reference/bit-rate-reduction-(brr)) — SNES 9-byte BRR block structure, 4-filter coefficients, loop point encoding.
- [VAG SPU-ADPCM Format](https://psx-spx.consoledev.net/soundprocessingunitspu/) — Sony PS1/PS2 16-byte ADPCM block structure, loop flags.
- [GameCube DSP-ADPCM Format](https://wiibrew.org/wiki/DSP-ADPCM) — Nintendo 8-byte frame audio codec, predictor coefficient tables.

### Text, Fonts & Localization
- [AngelCode BMFont](https://www.angelcode.com/products/bmfont/) — Bitmap font descriptor format (.fnt text and XML).
- [GNU gettext PO File Format](https://www.gnu.org/software/gettext/manual/gettext.html#PO-Files) — `.po` translation catalog structure and plural-form handling.
- [Romhacking.net TBL Format](https://www.romhacking.net/documents/313/) — Standard `.tbl` character mapping format for fan translation.
- [DTE / MTE Compression for ROM Hacking](https://www.romhacking.net/documents/208/) — Dual/Multi Tile Encoding bigram compression theory.

### Existing Tools & Prior Art
- [ndstool](https://github.com/devkitPro/ndstool) — Nintendo DS ROM header builder (reference for ARM9/ARM7 entry point layout).
- [Tinke](https://github.com/pleonex/tinke) — NDS graphic viewer (NCLR/NCGR/NSCR format reference).
- [Crystal Tile 2](https://www.romhacking.net/utilities/818/) — Tile editor (planar tile format documentation).
- [Lunar IPS / LIPS](https://www.romhacking.net/utilities/240/) — IPS patch format reference implementation.
- [xdelta3](https://github.com/jmacd/xdelta) — VCDIFF streaming delta compression reference.
- [pwntools](https://github.com/Gallopsled/pwntools) — CTF toolkit (library-first API design philosophy reference).
- [ndspy](https://github.com/RoadrunnerWMC/ndspy) — Nintendo DS Python library (ROM container design reference).

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
