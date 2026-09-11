# MioROM Cookbook & Golden Pipelines

The MioROM Cookbook contains production-ready, copy-pasteable recipes and end-to-end pipelines for common ROM hacking and game translation workflows.

Every recipe is 100% pure Python standard library—no external binaries or native extensions required.

---

## Recipe 1: Dialogue Extraction, Pointer Relinking, Checksum & Patching

When translating text that exceeds the original string length, strings must be relocated to free space and pointer tables updated, followed by checksum recalculation and patch emission.

```python
import struct
from miorom.scanner.text_stream import TextStreamScanner
from miorom.text.pointer_relinker import PointerRelinker
from miorom.core.checksum import RetroChecksum
from miorom.patch.bps import BpsPatcher

# 1. Load original ROM
with open("game.sfc", "rb") as f:
    rom = bytearray(f.read())

# 2. Scan and verify dialogue streams
scanner = TextStreamScanner(min_length=4, min_confidence=0.6)
dialogue_spans = scanner.scan(rom[0x1000:0x8000], encodings=["ascii"])

# 3. Scan existing pointer table (2-byte SNES LoROM pointers at $8000 base)
relinker = PointerRelinker(pointer_size=2, endian="little", base_address=0x8000)
records = relinker.scan_pointer_table(
    rom,
    table_offset=0x0800,
    entry_count=len(dialogue_spans),
    pointer_type="absolute",
)

# 4. Relink with new translations (automatically allocates free space when expanded)
translated_strings = [
    "PILIH PEMAIN\x00".encode("ascii"),
    "MULAI PETUALANGAN BARU SEKARANG\x00".encode("ascii"),
    # ...
]
modified_rom, report = relinker.relink(rom, records, translated_strings, fill_byte=0xFF)

# 5. Fix SNES internal cartridge checksum
sum_val, inv_val = RetroChecksum.snes_checksum(bytes(modified_rom))
modified_rom[0x7FDC:0x7FE0] = struct.pack("<HH", inv_val, sum_val)

# 6. Generate linear BPS distribution patch
patch_bytes = BpsPatcher.create(bytes(rom), bytes(modified_rom), metadata="MioROM Translation")
with open("game_v1.0.bps", "wb") as f:
    f.write(patch_bytes)
```

---

## Recipe 2: Code Cave Discovery, Branch Rebasing & Inline Trampoline Hooking

Inject custom machine code into unused ROM space, rebase PC-relative branch offsets, and install an inline branch hook that diverts execution to your payload and returns cleanly.

```python
from miorom.asm.hook_manager import CodeCaveManager, HookManager, ArmHookBuilder
from miorom.asm.reloc_calc import BranchRelocator
from miorom.asm.disasm import UniversalDisassembler

with open("game.gba", "rb") as f:
    rom = bytearray(f.read())

# 1. Find an unused region (runs of 0x00) with at least 64 bytes
cave_mgr = CodeCaveManager(fill_byte=0x00)
caves = cave_mgr.scan(rom, min_size=64)
cave, offset_in_cave = cave_mgr.allocate(32, label="item_drop_hook")
allocated_addr = cave.start + offset_in_cave

# 2. Prepare payload and rebase any PC-relative branches if moving existing code
payload_arm = bytes([
    0x01, 0x00, 0x80, 0xE2,  # add r0, r0, #1
    0x02, 0x10, 0x81, 0xE2,  # add r1, r1, #2
])

# 3. Install inline hook at hook_site (0x0500)
hook_site = 0x0500
hook_mgr = HookManager()
hook_rec = hook_mgr.install_arm_hook(
    buf=rom,
    hook_rom_offset=hook_site,
    hook_ram_addr=0x08000000 + hook_site,
    cave_ram_addr=0x08000000 + allocated_addr,
    cave_rom_offset=allocated_addr,
    cave_code=payload_arm,
    mode="b",
)

# 4. Verify disassembly of hook site and cave trampoline
disasm = UniversalDisassembler.disassemble(
    rom[hook_site:hook_site + 4],
    base_address=0x08000000 + hook_site,
    arch="arm",
    endian="little",
)
print(disasm[0].to_string())
```

---

## Recipe 3: Planar Graphics Decoding, Tile Deduplication & OAM Layout

Optimize tile data for VRAM constraints by eliminating duplicate tiles and symmetric flips, then generate hardware nametable entries and sprite attribute memory (OAM).

```python
from miorom.graphics.planar import PlanarTileCodec
from miorom.graphics.tile_dedup import TileDeduplicator
from miorom.graphics.oam import HardwareOamCodec, SpriteDescriptor

# 1. Load raw planar tile graphics (e.g. SNES 4bpp planar)
with open("tiles.bin", "rb") as f:
    raw_tiles = f.read()

# 2. Deduplicate raw tiles identifying horizontal and vertical flipped copies
opt_tiles, entries = TileDeduplicator.deduplicate_raw_bpp(
    raw_tiles,
    bpp=4,
    format="4bpp_planar",
    allow_flip_h=True,
    allow_flip_v=True,
)
print(f"Saved {len(raw_tiles) - len(opt_tiles)} bytes of VRAM!")

# 3. Generate SNES background nametable words
snes_nametable_words = [
    entry.to_nametable_word_snes(palette=1, priority=1)
    for entry in entries
]

# 4. Build 2D hardware sprites using the optimized tile indices
sprites = [
    SpriteDescriptor(x=64, y=100, tile_id=entries[0].unique_index, palette=1),
    SpriteDescriptor(x=72, y=100, tile_id=entries[1].unique_index, palette=1, flip_v=True),
]

# 5. Pack into SNES split OAM (Table 1 + Hi-OAM Table 2) or GBA OAM
table1, table2 = HardwareOamCodec.encode_snes(sprites)
gba_oam = HardwareOamCodec.encode_gba(sprites)
```

---

## Recipe 4: Cross-Version Binary Diffing & Function Matching

Identify matching subroutines between two game revisions (e.g. Japanese v1.0 and USA v1.1) to port modifications and hooks accurately across versions.

```python
from miorom.diff.bindiff import BinDiffEngine

with open("game_jp.dol", "rb") as f:
    data_jp = f.read()
with open("game_us.dol", "rb") as f:
    data_us = f.read()

base_address = 0x80003100

# 1. Discover potential function candidates from pointer tables
funcs_jp = BinDiffEngine.discover_function_candidates(data_jp, base_address, pointer_size=4)
funcs_us = BinDiffEngine.discover_function_candidates(data_us, base_address, pointer_size=4)

# 2. Diff CFG isomorphism across the two binaries
report = BinDiffEngine.diff_binaries(
    data_a=data_jp,
    base_a=base_address,
    funcs_a=funcs_jp,
    data_b=data_us,
    base_b=base_address,
    funcs_b=funcs_us,
    arch="ppc",
    threshold=0.80,
)

print(report.summary())
```

---

## Recipe 5: Anti-Piracy Detection & Surgical NOP Bypass

Scan retro executable binaries for anti-tamper loops and checksum validation vectors, applying targeted NOP patches.

```python
from miorom.asm.ap_bypass import AntiPiracyBypasser
from miorom.asm.disasm import UniversalDisassembler

with open("arm9.bin", "rb") as f:
    code = bytearray(f.read())

# 1. Scan for anti-piracy conditional branches
matches = AntiPiracyBypasser.scan_nds_ap(bytes(code))
print(f"Found {len(matches)} AP vectors.")

# 2. Apply surgical patches
report = AntiPiracyBypasser.patch_all(code, matches)
print(report.summary())
```
