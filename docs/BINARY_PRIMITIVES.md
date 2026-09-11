# Binary & Assembly Primitives

MioROM provides modular, low-level binary manipulation and assembly primitives designed for ROM hacking, localization engineering, and binary reverse engineering.

Rather than imposing monolithic workflows, these primitives act as composable building blocks that you integrate directly into custom extraction, patching, and repacking pipelines.

---

## Overview

| Primitive | Module | Purpose |
| :--- | :--- | :--- |
| `BinaryReader` | `miorom.core` | Endian-aware stream reader, zero-allocation static unpacker, and format gateway |
| `BinaryWriter` | `miorom.core` | Fluent binary stream writer, atomic packer, and in-place buffer mutator |
| `PatchWriter` | `miorom.patch` | Fluent binary patching with offset tracking and IPS generation |
| `UpsPatcher` | `miorom.patch` | Universal Patching System (UPS) with XOR diffing and CRC32 |
| `BpsPatcher` | `miorom.patch` | Modern Beat Patching System (BPS) creator and applier |
| `AsmSnippet` | `miorom.asm` | Pure-Python micro-assembler for ARM, Thumb, MIPS, PPC, SM83, and SNES |
| `SymbolicXrefEngine` | `miorom.asm` | Multi-architecture symbolic cross-reference discovery and call graphs |
| `CStructOverlay` | `miorom.core` | Interactive ANSI C struct parser compiling C declarations into binary layouts |
| `RecordBuilder` | `miorom.core` | Fluent binary struct and header serializer with alignment |
| `SymbolMap` | `miorom.core` | Symbol table with No$GBA `.sym` and Ghidra CSV export |
| `HexDiffHighlighter` | `miorom.core` | Terminal hex diff renderer with ANSI colors |
| `GameTextTemplate` | `miorom.text` | Bidirectional dialogue template engine |
| `BMFont` | `miorom.text` | AngelCode BMFont reader/writer with pure-Python PNG atlas packing |

---

## 1. Stream I/O & Atomic Packing — `BinaryReader` & `BinaryWriter`

`BinaryReader` and `BinaryWriter` provide fluent, endian-aware stream reading and writing, alongside zero-allocation static unpacking and atomic packing methods.

### Fluent Streaming I/O

```python
from miorom.core.binary import BinaryReader, BinaryWriter

# Writing binary streams
writer = BinaryWriter(endian=">")
writer.write_u32(0x12345678).write_u16(0xABCD).write_u8(0x42)
writer.write_string("Item_Name", encoding="utf-8", null_terminated=True)
writer.align(4, pad_byte=0x00)
data = writer.to_bytes()

# Reading binary streams
reader = BinaryReader(data, endian=">")
magic = reader.read_u32()
version = reader.read_u16()
flags = reader.read_u8()
name = reader.read_string(encoding="utf-8")
```

### Static Zero-Allocation Helpers & Format Gateway

Eliminates repetitive `struct.unpack_from` and `struct.pack` boilerplates:

```python
# Atomic unpacking without instantiating BytesIO
magic = BinaryReader.unpack_u32(rom_bytes, offset=0x1C, endian=">")
short_val = BinaryReader.unpack_s16(rom_bytes, offset=0x80, endian="<")
comp, chk = BinaryReader.unpack_from("<HH", rom_bytes, offset=0x7FDC)

# Atomic packing & in-place mutable buffer packing
header_magic = BinaryWriter.pack_u32(0x80371240, endian=">")
BinaryWriter.pack_into_u32(rom_buffer, offset=0x80, val=new_size, endian="<")
BinaryWriter.pack_into(">IH", rom_buffer, offset=0x200, 0xCAFEBABE, 0x1234)
```

---

## 2. Binary Patching — `PatchWriter` & Patcher Suite

`PatchWriter` provides a fluent interface for applying surgical modifications to binary buffers with automatic boundary checks, cursor management, and IPS patch emission.

**Key methods:**

- `write_at(offset, data)` — write raw bytes at an absolute offset
- `write_u8_at` / `write_u16_at` / `write_u32_at` — write typed integers
- `replace_range(start, end, data)` — overwrite a contiguous region
- `apply()` — return the patched buffer as `bytes`
- `build_ips()` — export the delta as a standard IPS patch file

MioROM also provides native pure-Python patchers:
- **`UpsPatcher`**: `create_file(src, tgt, patch)` and `apply_file(src, patch, out)` using XOR diffing and CRC32 verification.
- **`BpsPatcher`**: Full BPS v1 spec with source/target copy actions and checksums.
- **`IpsPatcher`**: Fast 16MB IPS patcher with constant-memory streaming support (`apply_stream`).

```python title="patch_arm9.py"
from miorom.patch import PatchWriter, UpsPatcher

rom_data = open("arm9.bin", "rb").read()
writer = PatchWriter(rom_data)

writer.write_at(0x000145A0, b"TRANSLATED_STRING\x00")
writer.write_u32_at(0x00010200, 0x020145A0, endian="<")
writer.replace_range(0x00010300, 0x00010320, b"\x00" * 32)

patched_bytes = writer.apply()

with open("patch.ips", "wb") as f:
    f.write(writer.build_ips())

# Or create a UPS patch directly between files:
UpsPatcher.create_file("source.gba", "modified.gba", "game.ups")
```

---

## 3. Micro-Assembly — `AsmSnippet`

`AsmSnippet` generates raw machine code for small function hooks, trampolines, and code caves — **no external cross-compiler required** (no devkitARM, no GCC).

=== "Thumb (16-bit)"

    | Method | Description |
    | :--- | :--- |
    | `push(regs)` / `pop(regs)` | Stack operations (r0-r7, LR/PC) |
    | `mov_imm` / `mov_reg` | Load immediate into register / register copy |
    | `add_imm` / `sub_imm` | 8-bit or 3-bit arithmetic with immediate |
    | `cmp_imm` / `cmp_reg` | Compare register with immediate or register |
    | `ldr_imm` / `str_imm` | Load / store 32-bit word relative to register |
    | `ldr_pc` / `ldr_sp` | Load literal from PC pool / SP stack |
    | `b` / `b_cond` | Relative unconditional or conditional branch |
    | `bl` / `bx` / `blx` | 32-bit branch-link, branch-exchange, BLX |
    | `nop()` | 16-bit NOP (`mov r8, r8`) |

=== "ARM32"

    | Method | Description |
    | :--- | :--- |
    | `push(regs)` / `pop(regs)` | Stack operations |
    | `mov_imm(rd, imm)` | Load immediate into register |
    | `add_imm` / `sub_imm` | Arithmetic with immediate |
    | `b` / `bl` / `bx` | Branch / branch-link / branch-exchange |
    | `nop()` | Padding instruction |

=== "PowerPC (PPC32)"

    | Method | Description |
    | :--- | :--- |
    | `stwu(rs, offset, ra)` | Store word with update (stack frame setup) |
    | `lwz` / `stw` | Load and store 32-bit words |
    | `li(rt, imm)` | Load 32-bit immediate (auto splits into `lis + ori`) |
    | `mr(ra, rs)` | Move register (`or ra, rs, rs`) |
    | `mflr` / `mtlr` | Move from/to Link Register |
    | `b` / `bl` / `blr` | Unconditional branch / branch-link / return |
    | `nop()` | PowerPC NOP (`ori r0, r0, 0`) |

=== "MIPS"

    | Method | Description |
    | :--- | :--- |
    | `lui` / `addiu` / `li` | Upper/lower immediate load (auto split) |
    | `lw` / `sw` | Load/store word |
    | `j` / `jal` / `jr_ra` | Jump / jump-and-link / return |
    | `nop()` | Branch delay slot padding |

=== "SNES (W65C816)"

    | Method | Description |
    | :--- | :--- |
    | `rep(flags)` / `sep(flags)` | Reset / Set processor flags (16-bit A/X/Y) |
    | `pha` / `pla` / `php` / `plp` | Push and pull accumulator or status |
    | `lda_imm` / `lda_addr` / `lda_long` | Load accumulator (8/16-bit, direct, long) |
    | `sta_addr` / `sta_long` | Store accumulator |
    | `jsr` / `jsl` / `rts` / `rtl` | Subroutine calls and returns (short/long) |
    | `nop()` | 65816 NOP (`0xEA`) |

=== "Game Boy (SM83)"

    | Method | Description |
    | :--- | :--- |
    | `ld_rr` / `ld_r_n` | Register and immediate loads |
    | `call` / `jp` / `jr` / `ret` | Control flow |
    | `push` / `pop` | Stack operations |
    | `cb(op, reg, bit)` | Bitwise CB prefix operations |

```python title="asm_hook.py"
from miorom.asm import AsmSnippet

# Thumb 16-bit hook (GBA / NDS)
thumb = AsmSnippet.thumb("<")
thumb.push(["r4", "lr"])
thumb.mov_imm("r0", 42)
thumb.bl(target_vaddr=0x08005200, current_pc=0x08001004)
thumb.pop(["r4", "pc"])
thumb_bytes = thumb.emit()

# PowerPC hook (GameCube / Wii)
ppc = AsmSnippet.ppc(">")
ppc.stwu("r1", -32, "r1")
ppc.mflr("r0")
ppc.stw("r0", 36, "r1")
ppc.li("r3", 0x80245000)
ppc.blr()
ppc_bytes = ppc.emit()

# SNES W65C816 hook
snes = AsmSnippet.snes()
snes.rep(0x20)  # 16-bit Accumulator
snes.lda_imm(0x1234, is_16bit=True)
snes.sta_addr(0x2100)
snes.sep(0x20)  # 8-bit Accumulator
snes.rts()
snes_bytes = snes.emit()
```

---

## 4. Struct Serialization — `RecordBuilder`

`RecordBuilder` constructs binary records, file headers, and metadata tables with exact field alignments — without brittle `struct.pack` format strings.

**Supported field types:** `u8`, `i8`, `u16`, `i16`, `u32`, `i32`, `u64`, `f32`, `fixed_str`, `pascal_str`, `bytes_field`, `align`

```python title="build_item_record.py"
from miorom.core import RecordBuilder

record = (
    RecordBuilder(endian="<")
    .u32(0x1001)
    .fixed_str("Herb of Mana", length=16, pad_byte=0x00)
    .pascal_str("Restores 50 HP", length_size=1)
    .u16(50)
    .align(4, pad_byte=0x00)
    .build()
)
```

!!! tip "Chaining"
    All builder methods return `self`, so calls can be chained in a single expression as shown above.

---

## 5. Symbol Management — `SymbolMap`

`SymbolMap` tracks function entrypoints, jump tables, string pools, and RAM variables — then exports them to debugger and disassembler formats.

**Symbol kinds:** `code`, `data`, `table`, `string`

```python title="export_symbols.py"
from miorom.core import SymbolMap

smap = SymbolMap()
smap.add(0x02001000, "fn_draw_dialogue", kind="code",  comment="Main text renderer")
smap.add(0x02002500, "tbl_dialogue_ptrs", kind="table", comment="Text pointer table")

with open("game.sym", "w", encoding="utf-8") as f:
    f.write(smap.export_sym_file())

with open("ghidra_labels.csv", "w", encoding="utf-8") as f:
    f.write(smap.export_csv())
```

---

## 6. Hex Diff Inspection — `HexDiffHighlighter`

`HexDiffHighlighter` renders colorized hex diffs in the terminal — lets you visually verify every changed byte **before** writing to disk.

```python title="verify_patch.py"
from miorom.core import HexDiffHighlighter

HexDiffHighlighter.print_diff(
    original=original_bytes,
    modified=patched_bytes,
    offset=0x1000,
    size=64,
    use_color=True,
)
```

!!! note "Output format"
    Modified lines are prefixed with `*`. Unchanged lines are shown normally for context.

---

## 7. Dialogue Templates — `GameTextTemplate`

`GameTextTemplate` provides bidirectional parsing for dialogue strings that contain embedded control tags, actor variables, and item parameters.

```python title="dialogue_template.py"
from miorom.text import GameTextTemplate

tmpl = GameTextTemplate("Hello [HERO:{name}], you received {count}x [ITEM:{item}]!")

rendered = tmpl.render(name="Raguna", count=3, item="Turnip")
# → "Hello [HERO:Raguna], you received 3x [ITEM:Turnip]!"

data = tmpl.extract(rendered)
# → {"name": "Raguna", "count": "3", "item": "Turnip"}
```

---

## 8. C Struct Modeling — `CStructOverlay`

`CStructOverlay` parses ANSI C struct declarations and provides a pythonic overlay mapping directly over binary buffers. It supports nested structs, fixed-length arrays/strings, attribute access (`monster.hp`), dictionary access, table iterations, and in-place binary writes.

```python title="parse_c_struct.py"
from miorom.core import CStructOverlay

c_decl = """
struct Enemy {
    uint16_t id;
    char name[16];
    int16_t hp;
    int16_t max_hp;
    uint8_t attack;
    uint8_t defense;
    uint32_t exp;
};
"""

overlay = CStructOverlay.from_c(c_decl, endian="<", pack_alignment=1)
print(f"Struct size: {overlay.size} bytes")  # 28 bytes

# Read an entire table of enemies from ROM
enemies = overlay.read_table(rom_data, offset=0x02005000, count=10)
for enemy in enemies:
    print(f"[{enemy.id}] {enemy.name} - HP: {enemy.hp}/{enemy.max_hp}")

# Modify and pack back in-place
enemies[0].hp = 999
overlay.write(rom_data_bytearray, offset=0x02005000, record=enemies[0])
```

---

## 9. Symbolic Cross-References — `SymbolicXrefEngine`

`SymbolicXrefEngine` analyzes multi-architecture machine code and pointer structures to discover bidirectional relationships between code and data. It identifies literal pool references, split immediates, direct calls, and jump branches, with IDA/Ghidra-style comment generation.

```python title="analyze_xrefs.py"
from miorom.asm import SymbolicXrefEngine, UniversalDisassembler

# Scan ARM9 code segment
db = SymbolicXrefEngine.analyze(arm9_bytes, base_address=0x02000000, arch="arm", endian="<")

# Query inbound calls
callers = db.callers_of(0x02004500)
print(f"Functions calling sub_02004500: {[hex(c) for c in callers]}")

# Generate IDA / Ghidra style annotated disassembly
instructions = UniversalDisassembler.disassemble(arm9_bytes[:256], base_address=0x02000000, arch="arm")
annotated_lines = db.annotate_disassembly(instructions)
for line in annotated_lines:
    print(line)
```

---

## 10. AngelCode BMFont & Texture Packing — `BMFont`

`BMFont` provides two-way serialization for AngelCode `.fnt` files (both Text and XML variants), automatic 2D texture atlas shelf packing, and built-in pure-Python PNG encoding/decoding without requiring PIL/Pillow.

```python title="bmfont_workflow.py"
from miorom.text import BMFont, BitmapFont, PNGCodec

# 1. Load an existing AngelCode font
font = BMFont.from_text(open("dialogue.fnt").read())
print(f"Font: {font.info.face}, Line Height: {font.common.line_height}, Glyphs: {len(font.chars)}")

# 2. Pack a BitmapFont into a 2D atlas texture sheet + pure Python PNG
bf = BitmapFont(default_height=12)
# ... add glyphs ...
bmfont, raw_atlas, png_bytes = BMFont.from_bitmap_font(
    bf, page_file="font_atlas.png", texture_width=256, texture_height=256
)

with open("font_atlas.png", "wb") as f:
    f.write(png_bytes)

with open("font.fnt", "w") as f:
    f.write(bmfont.to_text())
```

---

## Full Pipeline Example

```python title="translation_pipeline.py"
from miorom.patch import PatchWriter
from miorom.core import RecordBuilder, SymbolMap, HexDiffHighlighter
from miorom.text import GameTextTemplate

# 1. Symbol table
symbols = SymbolMap()
symbols.add(0x00010000, "ptr_table", kind="table", comment="Message pointer table")
symbols.add(0x00018000, "text_pool",  kind="data",  comment="Relocated string pool")

# 2. Render translated dialogue
tmpl = GameTextTemplate("[ACTOR:{actor}] {message}")
translated_lines = [
    tmpl.render(actor="Mist",   message="Good morning! Welcome to the farm."),
    tmpl.render(actor="Raguna", message="Thank you, I will do my best."),
]

# 3. Serialize pointer table + string pool
pool_builder  = RecordBuilder(endian="<")
table_builder = RecordBuilder(endian="<")

current_offset = symbols["text_pool"]
for line in translated_lines:
    table_builder.u32(current_offset)
    encoded = line.encode("utf-8") + b"\x00"
    pool_builder.bytes_field(encoded)
    current_offset += len(encoded)

new_table = table_builder.build()
new_pool  = pool_builder.build()

# 4. Patch ROM
rom_data = open("game_original.bin", "rb").read()
patcher  = PatchWriter(rom_data)
patcher.write_at(symbols["ptr_table"], new_table)
patcher.write_at(symbols["text_pool"],  new_pool)
patched_rom = patcher.apply()

# 5. Audit changes
HexDiffHighlighter.print_diff(
    original=rom_data,
    modified=patched_rom,
    offset=symbols["ptr_table"],
    size=len(new_table),
    use_color=True,
)

# 6. Save output
with open("game_patched.bin", "wb") as f:
    f.write(patched_rom)
```
