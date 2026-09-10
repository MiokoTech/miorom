# Binary & Assembly Primitives

MioROM provides modular, low-level binary manipulation and assembly primitives designed for ROM hacking, localization engineering, and binary reverse engineering.

Rather than imposing monolithic workflows, these primitives act as composable building blocks that you integrate directly into custom extraction, patching, and repacking pipelines.

---

## Overview

| Primitive | Module | Purpose |
| :--- | :--- | :--- |
| `PatchWriter` | `miorom.patch` | Fluent binary patching with offset tracking and IPS generation |
| `AsmSnippet` | `miorom.asm` | Pure-Python micro-assembler for ARM32 and MIPS sequences |
| `RecordBuilder` | `miorom.core` | Fluent binary struct and header serializer with alignment |
| `SymbolMap` | `miorom.core` | Symbol table with No$GBA `.sym` and Ghidra CSV export |
| `HexDiffHighlighter` | `miorom.core` | Terminal hex diff renderer with ANSI colors |
| `GameTextTemplate` | `miorom.text` | Bidirectional dialogue template engine |

---

## 1. Binary Patching — `PatchWriter`

`PatchWriter` provides a fluent interface for applying surgical modifications to binary buffers with automatic boundary checks, cursor management, and IPS patch emission.

**Key methods:**

- `write_at(offset, data)` — write raw bytes at an absolute offset
- `write_u8_at` / `write_u16_at` / `write_u32_at` — write typed integers
- `replace_range(start, end, data)` — overwrite a contiguous region
- `apply()` — return the patched buffer as `bytes`
- `build_ips()` — export the delta as a standard IPS patch file

```python title="patch_arm9.py"
from miorom.patch import PatchWriter

rom_data = open("arm9.bin", "rb").read()
writer = PatchWriter(rom_data)

writer.write_at(0x000145A0, b"TRANSLATED_STRING\x00")
writer.write_u32_at(0x00010200, 0x020145A0, endian="<")
writer.replace_range(0x00010300, 0x00010320, b"\x00" * 32)

patched_bytes = writer.apply()

with open("patch.ips", "wb") as f:
    f.write(writer.build_ips())
```

---

## 2. Micro-Assembly — `AsmSnippet`

`AsmSnippet` generates raw machine code for small function hooks, trampolines, and code caves — **no external cross-compiler required** (no devkitARM, no GCC).

=== "ARM32"

    | Method | Description |
    | :--- | :--- |
    | `push(regs)` / `pop(regs)` | Stack operations |
    | `mov_imm(rd, imm)` | Load immediate into register |
    | `add_imm` / `sub_imm` | Arithmetic with immediate |
    | `b` / `bl` / `bx` | Branch / branch-link / branch-exchange |
    | `nop()` | Padding instruction |

=== "MIPS"

    | Method | Description |
    | :--- | :--- |
    | `lui` / `addiu` / `li` | Upper/lower immediate load (auto split) |
    | `lw` / `sw` | Load/store word |
    | `j` / `jal` / `jr_ra` | Jump / jump-and-link / return |
    | `nop()` | Branch delay slot padding |

=== "Game Boy (SM83)"

    | Method | Description |
    | :--- | :--- |
    | `ld_rr` / `ld_imm` | Register and immediate loads |
    | `call` / `jp` / `jr` / `ret` | Control flow |
    | `push` / `pop` | Stack operations |

```python title="asm_hook.py"
from miorom.asm import AsmSnippet

# ARM32 trampoline hook
arm = AsmSnippet.arm("<")
arm.push(["r4", "r5", "lr"])
arm.mov_imm("r0", 42)
arm.add_imm("r1", "r0", 10)
arm.bx("lr")
arm_code = arm.emit()

# MIPS routine (PS1 / N64)
mips = AsmSnippet.mips(">")
mips.li("a0", 0x80041A20)
mips.lw("v0", "a0", 0)
mips.sw("v0", "sp", 16)
mips.jr_ra()
mips_code = mips.emit()
```

---

## 3. Struct Serialization — `RecordBuilder`

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

## 4. Symbol Management — `SymbolMap`

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

## 5. Hex Diff Inspection — `HexDiffHighlighter`

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

## 6. Dialogue Templates — `GameTextTemplate`

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
