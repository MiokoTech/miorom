# MioROM

<div class="retro-hero">
  <div class="title">&gt; MIOROM // RE_FRAMEWORK_v1.0.0</div>
  <div class="subtitle">Modular Low-Level Binary &amp; Assembly Primitives for Console ROM Hacking</div>
  <div>
    <span class="chip-badge nds">NDS ARM9/ARM7/THUMB</span>
    <span class="chip-badge n64">N64 MIPS-VR4300</span>
    <span class="chip-badge gba">GBA ARM7TDMI</span>
    <span class="chip-badge wii">WII BROADWAY PPC</span>
    <span class="chip-badge ps1">PS1 MIPS-R3000A</span>
    <span class="chip-badge snes">SNES W65C816</span>
    <span class="chip-badge nes">NES MOS-6502</span>
    <span class="chip-badge gba">SEGA M68000</span>
    <span class="chip-badge nds">GB SM83</span>
  </div>
  <div class="stats">
    <span>TESTS: <strong>1050+ PASSED</strong></span>
    <span>RUNTIME DEPS: <strong>ZERO (STDLIB ONLY)</strong></span>
    <span>DISASSEMBLER: <strong>8 ARCHITECTURES</strong></span>
    <span>LICENSE: <strong>MIT</strong></span>
  </div>
</div>

**MioROM** is an advanced Python framework and low-level primitive library designed for ROM hacking, game localization engineering, and binary reverse engineering.

Rather than imposing a monolithic graphical interface or rigid one-click workflows, MioROM delivers foundational programmatic building blocks: declarative struct modeling, progressive streaming scanners, micro-assembly emitters, and multi-architecture SSA IR decompilers. Developers assemble these primitives directly into bespoke, reproducible extraction, translation, and repacking toolchains.

---

## Supported Systems & Targets

| Architecture / Platform | Binary Formats | Primary Primitives |
|---|---|---|
| <span class="chip-badge nds">Nintendo DS</span> | `.nds`, `.srl`, `.narc`, `.nftr`, `.ncgr`, `.nclr`, `.nscr` | `NDSRom`, `NARCArchive`, `NFTRFont`, `NCLRFile`, `NCGRFile`, `NSCRFile`, `ThumbSnippet`, FAT/FNT mapper |
| <span class="chip-badge n64">Nintendo 64</span> | `.z64`, `.n64`, `.v64`, `.m64` | `N64Rom`, `DmaTableArchive`, `Fast3DParser`, `Fast3DBuilder`, `N64TextureDecoder`, `Yay0`, IPL3 CIC verification |
| <span class="chip-badge gba">Game Boy Advance</span> | `.gba`, `.agb`, `.bin` | `GBARom`, `LZ10`, `LZ11`, `ArmSnippet`, `ThumbSnippet`, `APLib`, complement check validation |
| <span class="chip-badge wii">Wii / GameCube</span> | `.iso`, `.gcm`, `.u8`, `.arc`, `.tpl`, `.dol` | `GameCubeDisc`, `U8Archive`, `TPLFile`, `DolBinary`, `PpcSnippet`, `DSPADPCMCodec`, `Yay0`, `Yaz0`, 32-byte alignment |
| <span class="chip-badge ps1">PlayStation 1</span> | `.bin/.cue`, `.iso`, `.exe`, `.tim`, `.vag` | `ISO9660`, `CueBinDisc`, `TIMImage`, `PSXExe`, `VAGFile`, `VAGCodec` (SPU-ADPCM), `CdXaDecoder` |
| <span class="chip-badge snes">Super Nintendo</span> | `.sfc`, `.smc`, `.brr` | `SNESRom`, `BRRCodec` (SPC700 audio), `SnesSnippet`, W65C816 disasm with dynamic REP/SEP tracking |
| <span class="chip-badge nes">NES / Famicom</span> | `.nes`, `.unf` | `NESRom`, `NESHeaderStruct` (iNES / NES 2.0), mapper identification, PRG/CHR separation, MOS 6502 disasm |
| <span class="chip-badge gba">Sega Genesis / MD</span> | `.md`, `.gen`, `.smd` | `MDRom`, SMD deinterleaving, Motorola 68000 disasm &amp; lifter |
| <span class="chip-badge nds">Game Boy / GBC</span> | `.gb`, `.gbc` | `GBRom`, `SM83Snippet`, SM83 instruction disassembler &amp; IR lifter |

---

## Core Primitives at a Glance

### 1. Declarative Binary Struct Modeling (`BinaryStruct`)
Stop writing brittle manual `struct.unpack_from("<IIH", data, offset)`. Define binary structures cleanly with typed fields, dynamic lengths, bitfields, and automated validation:

```python
from miorom.core.schema import BinaryStruct, FixedString, U16, U32, EnumField, ParseError
from enum import IntEnum

class CompressionType(IntEnum):
    NONE = 0x00
    LZ10 = 0x10
    LZ11 = 0x11
    YAZ0 = 0x20

class RomHeader(BinaryStruct):
    _endian = "<"
    magic = FixedString(4, default="ROM1")
    version = U16(default=1, validate=lambda v: v >= 1)
    compression = EnumField(U16(), CompressionType)
    file_count = U32()

# Unpack from raw binary bytes
header = RomHeader.from_bytes(raw_bytes)
print(header.magic)        # "ROM1"
print(header.compression)  # CompressionType.LZ11

# Modify and serialize back
header.version = 2
packed_bytes = header.to_bytes()
```

---

### 2. Multi-Architecture SSA IR Decompilation (`BinaryLifter`)
Lift raw machine code from PowerPC, ARM32, MIPS32 (including COP1 floats), SM83, and M68K into an architecture-neutral Static Single Assignment (SSA) Micro-IR, and decompile directly into readable C pseudocode:

```python
from miorom.script.lifter import BinaryLifter

# MIPS machine code snippet (e.g. from N64 or PS1)
mips_bytes = bytes.fromhex("2404002A 8C820000 03E00008 00000000")

# Lift to SSA Intermediate Representation
ir = BinaryLifter.lift(mips_bytes, base_address=0x80001000, arch="mips", endian=">")

# Generate human-readable C pseudocode
c_code = BinaryLifter.decompile_to_c(ir)
print(c_code)
# Output:
# int sub_80001000() {
#     int $a0_1, $v0_1;
# loc_80001000:
#     $a0_1 = 0x2A;
#     $v0_1 = *($a0_1);
#     return $v0_1;
# }
```

---

### 3. Fast3D Texture Codecs & Display List Parsing
Extract and inject N64 Fast3D graphics textures (`RGBA32`, `RGBA16`, `IA16`, `I8`, `CI8`) directly into transparent PNGs, or parse microcode commands straight from display lists:

```python
from miorom.graphics import N64TextureDecoder, N64TextureEncoder, Fast3DParser

# Decode raw N64 RGBA32 binary bytes to PNG
N64TextureDecoder.to_png(raw_bytes, fmt="rgba32", width=32, height=32, output_path="icon.png")

# Re-encode edited PNG back to native N64 binary bytes
n64_binary = N64TextureEncoder.from_image("icon_edited.png", fmt="rgba32")

# Parse display list microcode stream (G_SETTIMG, G_SETTILE, G_SETTILESIZE)
textures = Fast3DParser.find_textures(display_list_bytes)
for tex in textures:
    print(f"Discovered {tex.format_name} ({tex.width}x{tex.height}) at 0x{tex.image_ptr:08X}")
```

---

### 4. Dialogue Localization & Clean Script Catalogs
Extract complex dialogue with variable-width fonts, sanitize pointer artifacts, and export clean human-readable scripts formatted in `[id]\ntext`:

```python
from miorom.formats.script_catalog import DialogueCleaner, ScriptCatalog

# Strip binary pointer noise, raw hex tags, and format clean newlines
clean_text = DialogueCleaner.clean("<1A><13>-<08>You found the <05>AFairy Bow<05>@!<01>Shoot it with B.")
print(clean_text)
# Output:
# You found the AFairy Bow@!
# Shoot it with B.

# Dump translation rows to plain human-readable [id] script file
ScriptCatalog.dump_script("script.txt", translation_rows, clean=True)

# Synchronize edited script back into CSV translation columns
ScriptCatalog.script_to_csv("script_translated.txt", "base.csv", "updated.csv")
```

---

### 5. Fan Translation Reverse Engineering Toolkit
Surgical primitives for dissecting and translating retro game ROMs:
- **`JapaneseCharMapMiner`**: Gojūon relative search engine auto-generating draft `.tbl` character tables from raw ROM binaries.
- **`FontDissector`**: Heuristic font scanner, VWF width table hunter, and PNG spritesheet round-trip pipeline.
- **`TextCompressionHunter`**: Retro Huffman tree graph walker and DTE bigram forensic scanner with optimal re-compressor.
- **`ScriptVMDissector`**: Event script bytecode disassembler and branch relinker recalculating all jump targets automatically.
- **`TilemapDissector`**: Menu nametable text scanner, ASCII layout visualizer, and translated graphic label splicer.
- **`VWFHookEngine`**: End-to-end VWF hook deployer across ARM32, Thumb, MIPS32, SNES 65816, and MOS 6502 with automatic code cave allocation.

---

## Installation

Install MioROM from PyPI:

```bash
pip install miorom
```

Or install the latest development tree directly from GitHub:

```bash
pip install git+https://github.com/MiokoTech/miorom
```

---

## Documentation Navigation

<div class="grid cards" markdown>

-   :material-book-open-page-variant: **[Workflow Guide](WORKFLOW_GUIDE.md)**
    ---
    End-to-end tutorial: from untouched ROM to distributed binary patch.

-   :material-chip: **[Binary & Assembly Primitives](BINARY_PRIMITIVES.md)**
    ---
    Fluent binary reader/writers, micro-assemblers (`MipsSnippet`, `ArmSnippet`), patch writers, and symbol maps.

-   :material-console: **[CLI Reference](CLI_REFERENCE.md)**
    ---
    Terminal manual for `miorom unpack`, `repack`, `scan`, `diff`, and more.

-   :material-chef-hat: **[Cookbook & Golden Pipelines](COOKBOOK.md)**
    ---
    10 golden pipelines: NDS, GBA, SNES, N64, GC, PS1, Sega, and PC-Engine recipes.

-   :material-gamepad: **[Platform Specifications](PLATFORMS.md)**
    ---
    Technical format breakdown for NDS, Wii, GC, N64, GBA, SNES, and Mega Drive.

-   :material-puzzle: **[Plugin Guide](PLUGIN_GUIDE.md)**
    ---
    Register custom console handlers and codecs via `RomManager` or `entry_points`.

-   :material-code-json: **[API Reference](API_REFERENCE.md)**
    ---
    Complete programmatic index across 70+ classes and all 10 core subpackages.

-   :material-file-certificate: **[Library Contracts](LIBRARY_CONTRACTS.md)**
    ---
    Serialization, streaming, structured exceptions, and pipeline extension contracts.

-   :material-shield-check: **[Security & Path Safety](SECURITY.md)**
    ---
    Directory traversal protection, zip-slip defense, and untrusted archive checklist.

-   :material-history: **[Release Changelog](CHANGELOG.md)**
    ---
    Detailed version history, migration notes, and v1.0.0 release summary.

</div>
