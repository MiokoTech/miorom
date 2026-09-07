# MioROM Binary & Assembly Primitives Guide

MioROM provides modular, low-level binary manipulation and assembly primitives designed for ROM hacking, localization engineering, and binary reverse engineering.

Rather than imposing monolithic, opinionated workflows, these primitives offer programmatic building blocks that developers integrate directly into custom extraction, patching, and repacking scripts.

---

## Architecture Overview

MioROM categorizes its low-level primitives into six specialized components:

| Primitive | Module | Primary Purpose |
| :--- | :--- | :--- |
| `PatchWriter` | `miorom.patch` | Fluent binary patching with offset tracking and IPS generation |
| `AsmSnippet` | `miorom.asm` | Pure-Python micro-assembler for ARM32 and MIPS instruction sequences |
| `RecordBuilder` | `miorom.core` | Fluent binary struct and header serializer with alignment support |
| `SymbolMap` | `miorom.core` | Reverse engineering symbol table with No$GBA (.sym) and Ghidra CSV export |
| `HexDiffHighlighter` | `miorom.core` | Terminal hex diff formatter with ANSI color-coded verification |
| `GameTextTemplate` | `miorom.text` | Bidirectional dialogue template engine with dynamic control tags |

---

## 1. Binary Patching (`PatchWriter`)

`PatchWriter` provides a fluent interface for applying surgical modifications to binary buffers with automatic boundary checks, cursor management, and IPS patch emission.

### Key Capabilities
- Chainable writes: `write_at`, `write_u8_at`, `write_u16_at`, `write_u32_at`.
- Range replacement and zero-fill: `replace_range`.
- Audit history: `records` property tracking every contiguous change.
- Multi-target export: in-memory byte buffers via `apply()` or IPS format via `build_ips()`.

### Example
```python
from miorom.patch import PatchWriter

rom_data = open("arm9.bin", "rb").read()
writer = PatchWriter(rom_data)

# Apply modifications
writer.write_at(0x000145A0, b"TRANSLATED_STRING\x00")
writer.write_u32_at(0x00010200, 0x020145A0, endian="<")
writer.replace_range(0x00010300, 0x00010320, b"\x00" * 32)

# Generate modified binary
patched_bytes = writer.apply()

# Export IPS patch
ips_data = writer.build_ips()
with open("patch.ips", "wb") as f:
    f.write(ips_data)
```

---

## 2. Micro-Assembly Generation (`AsmSnippet`)

`AsmSnippet` generates raw machine code sequences for small function hooks, trampolines, and code caves without requiring an external cross-compiler toolchain (devkitARM, GCC).

### Architecture Support

#### ARM32 (`AsmSnippet.arm`)
- Stack operations: `push`, `pop`.
- Register operations: `mov_imm`, `add_imm`, `sub_imm`.
- Branches: `b` (relative branch), `bl` (branch with link), `bx` (branch exchange).
- Instruction padding: `nop`.

#### MIPS (`AsmSnippet.mips`)
- Register operations: `lui`, `addiu`.
- Control flow: `jr_ra` (jump register with branch delay slot handling).
- Instruction padding: `nop`.

### Example
```python
from miorom.asm import AsmSnippet

# ARM32 hook routine
arm = AsmSnippet.arm("<")
arm.push(["r4", "r5", "lr"])
arm.mov_imm("r0", 42)
arm.add_imm("r1", "r0", 10)
arm.bx("lr")
arm_machine_code = arm.emit()

# MIPS routine (PS1 / N64 / PS2)
mips = AsmSnippet.mips(">")
mips.lui("v0", 0x8004)
mips.addiu("v0", "v0", 0x1A20)
mips.jr_ra()
mips_machine_code = mips.emit()
```

---

## 3. Binary Struct Serialization (`RecordBuilder`)

`RecordBuilder` constructs binary data records, file headers, and metadata tables with exact field alignments, fixed-width strings, and Pascal strings without brittle `struct.pack` format strings.

### Key Capabilities
- Numeric types: `u8`, `i8`, `u16`, `i16`, `u32`, `i32`, `u64`, `f32`.
- Fixed-width strings with configurable padding byte: `fixed_str(text, length, pad_byte)`.
- Length-prefixed Pascal strings: `pascal_str(text, length_size)`.
- Explicit memory alignment: `align(boundary, pad_byte)`.

### Example
```python
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

---

## 4. Address & Symbol Management (`SymbolMap`)

`SymbolMap` acts as an address book for reverse engineering sessions, tracking function entrypoints, jump tables, string pools, and RAM variables.

### Key Capabilities
- Symbol categorization: `code`, `data`, `table`, `string`.
- Bidirectional lookup: lookup by address or symbol name.
- Export to No$GBA emulator symbol file (`.sym`).
- Export to Ghidra importable CSV.
- Import from existing `.sym` files.

### Example
```python
from miorom.core import SymbolMap

smap = SymbolMap()
smap.add(0x02001000, "fn_draw_dialogue", kind="code", comment="Main text renderer")
smap.add(0x02002500, "tbl_dialogue_ptrs", kind="table", comment="Text pointer table")

# Export for debugging tools
with open("game.sym", "w", encoding="utf-8") as f:
    f.write(smap.export_sym_file())

with open("ghidra_labels.csv", "w", encoding="utf-8") as f:
    f.write(smap.export_csv())
```

---

## 5. Terminal Hex Diff Inspection (`HexDiffHighlighter`)

`HexDiffHighlighter` provides terminal-based visual verification of binary modifications, rendering colored hex diffs before committing patches to disk.

### Key Capabilities
- Side-by-side or inline view of original vs modified bytes.
- ANSI color highlighting (green for additions/modifications, red for original bytes).
- Line modification indicator (`*`).
- Configurable bytes-per-line and range offsets.

### Example
```python
from miorom.core import HexDiffHighlighter

HexDiffHighlighter.print_diff(
    original=original_bytes,
    modified=patched_bytes,
    offset=0x1000,
    size=64,
    use_color=True,
)
```

---

## 6. Dialogue Tag Templating (`GameTextTemplate`)

`GameTextTemplate` provides bidirectional parsing and formatting for game dialogue strings containing embedded control tags, actor variables, and item parameters.

### Key Capabilities
- Dynamic variable parsing: `variables`.
- String interpolation: `render(**kwargs)`.
- Reverse parameter extraction: `extract(text)`.

### Example
```python
from miorom.text import GameTextTemplate

tmpl = GameTextTemplate("Hello [HERO:{name}], you received {count}x [ITEM:{item}]!")
rendered = tmpl.render(name="Raguna", count=3, item="Turnip")

# Reverse extraction
data = tmpl.extract(rendered)
# -> {"name": "Raguna", "count": "3", "item": "Turnip"}
```

---

## 7. Complete Pipeline Integration

The following script demonstrates combining these primitives into an automated ROM translation repacking pipeline:

```python
from miorom.patch import PatchWriter
from miorom.core import RecordBuilder, SymbolMap, HexDiffHighlighter
from miorom.text import GameTextTemplate

# 1. Initialize symbol addresses
symbols = SymbolMap()
symbols.add(0x00010000, "ptr_table", kind="table", comment="Message pointer table")
symbols.add(0x00018000, "text_pool", kind="data", comment="Relocated string pool")

# 2. Format dialogue strings
tmpl = GameTextTemplate("[ACTOR:{actor}] {message}")
translated_lines = [
    tmpl.render(actor="Mist", message="Good morning! Welcome to the farm."),
    tmpl.render(actor="Raguna", message="Thank you, I will do my best."),
]

# 3. Serialize pointer table and string pool
pool_builder = RecordBuilder(endian="<")
table_builder = RecordBuilder(endian="<")

current_offset = symbols["text_pool"]
for line in translated_lines:
    table_builder.u32(current_offset)
    encoded = line.encode("utf-8") + b"\x00"
    pool_builder.bytes_field(encoded)
    current_offset += len(encoded)

new_table = table_builder.build()
new_pool = pool_builder.build()

# 4. Apply patches into ROM
rom_data = open("game_original.bin", "rb").read()
patcher = PatchWriter(rom_data)
patcher.write_at(symbols["ptr_table"], new_table)
patcher.write_at(symbols["text_pool"], new_pool)

patched_rom = patcher.apply()

# 5. Visually audit changes
HexDiffHighlighter.print_diff(
    original=rom_data,
    modified=patched_rom,
    offset=symbols["ptr_table"],
    size=len(new_table),
    use_color=True,
)

# 6. Write output binary
with open("game_patched.bin", "wb") as f:
    f.write(patched_rom)
```
