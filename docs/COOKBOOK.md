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

---

## Recipe 6: GBA ROM Expansion, Pointer Relinking & SRAM Flashcart Patching

Translate text in a Game Boy Advance ROM by expanding cartridge capacity, relinking dialogue pointers to new memory space, converting Flash saves to SRAM for flashcarts, and repairing the complement checksum.

```python
from miorom.platforms.gba import GBARom

# 1. Load pristine GBA ROM
rom = GBARom.from_file("game.gba")
print(f"Loaded: {rom.title} [{rom.game_code}] - Region: {rom.region}")

# 2. Expand capacity from 8 MB to 16 MB with 0xFF padding
if len(rom.data) < 16 * 1024 * 1024:
    rom.expand(16)

# 3. Relink dialogue table pointers
old_script_offset = 0x00150000
new_script_offset = 0x00900000  # in expanded free space

# Write translated dialogue to new offset
translated_script = b"WELCOME TO THE NEW ADVENTURE!\x00"
rom.data[new_script_offset : new_script_offset + len(translated_script)] = translated_script

# Automatically locate and relink all 32-bit pointers
relinked_count = rom.relink_pointers(old_script_offset, new_script_offset)
print(f"Relinked {relinked_count} pointers to 0x{new_script_offset:X}.")

# 4. Patch save to SRAM for flashcart/emulator compatibility if needed
if "FLASH" in rom.detect_save_type():
    rom.patch_save_to_sram()
    print("Converted Flash backup calls to SRAM.")

# 5. Fix complement checksum and save
rom.save("game_translated.gba", fix_checksum=True)
print("Saved translated ROM with valid complement checksum.")
```

---

## Recipe 7: PS1 Disc Asset Replacement, Executable Patching & EDC Recalculation

Replace in-game assets and patch the MIPS boot executable inside a PlayStation 1 Mode 2 Form 1 BIN disc image with bit-exact 32-bit EDC checksum recalculation.

```python
from miorom.platforms.psx import PSXRom

# 1. Open Mode 2 Form 1 CD-ROM BIN image (2352 bytes/sector)
psx = PSXRom.from_file("game.bin")
print(f"Boot Path: {psx.boot_path}, Region: {psx.region}")

# 2. Replace localized dialogue script inside virtual filesystem
with open("translated_script.dat", "rb") as f:
    new_script = f.read()
psx.replace_file("DATA/SCRIPT.DAT", new_script)

# 3. Patch MIPS boot executable (e.g. font width lookup table)
main_exe = psx.get_main_exe()
if main_exe:
    # Modify MIPS binary or text section in memory
    main_exe.text_data[0x200:0x204] = b"\x00\x00\x00\x00"  # NOP check
    psx.replace_main_exe(main_exe)

# 4. Rebuild disc with bit-exact EDC calculation
psx.save("game_mod.bin")

# 5. Generate companion CUE sheet for emulators
with open("game_mod.cue", "w") as f:
    f.write(psx.generate_cue("game_mod.bin"))
print("Saved game_mod.bin and game_mod.cue successfully.")
```

---

## Recipe 8: Nintendo Wii Disc Decryption, FST File Replacement & Trucha Bug Signing

Decrypt retail Nintendo Wii optical disc images on-the-fly, replace localized script files inside the encrypted partition FST filesystem, and repack with Trucha Bug fake-signing.

```python
from miorom.platforms.wii import WiiDisc

# 1. Open raw retail ISO or WBFS disc image
disc = WiiDisc.from_file("game.iso")
print(f"Title: {disc.header.game_title} [{disc.header.game_id}]")

# 2. Extract and modify in-game message binary
partition = disc.get_data_partition()
old_script = partition.read_file("DATA/files/message/dialogue.bin")

with open("dialogue_en.bin", "rb") as f:
    translated_script = f.read()

# 3. Replace file inside encrypted partition FST (auto-reindexes cluster allocations)
partition.replace_file("DATA/files/message/dialogue.bin", translated_script)

# 4. Save modified disc with Trucha bug fake-signing
disc.save("game_translated.iso", fake_sign=True)
print("Saved game_translated.iso with valid Trucha signature.")
```

---

## Recipe 9: Nintendo DS 2D Sprite Assembly & Animation Sequence Pipeline

Load Nitro character graphics, palettes, cell definitions, and keyframe animations, modify animation frame delays, and render composite sprite frames to PNG.

```python
from miorom.platforms.nds import NCERFile, NCGRFile, NCLRFile, NANRFile

# 1. Load Nitro 2D graphics suite components
ncgr = NCGRFile.from_bytes(open("sprite.ncgr", "rb").read())
nclr = NCLRFile.from_bytes(open("sprite.nclr", "rb").read())
ncer = NCERFile.from_bytes(open("sprite.ncer", "rb").read())
nanr = NANRFile.from_bytes(open("anim.nanr", "rb").read())

# 2. Render first frame of walk animation
first_seq = nanr.sequences[0]
first_cell_idx = first_seq.frames[0].cell_index
sprite_image = ncer.render_cell(bank_index=first_cell_idx, ncgr=ncgr, nclr=nclr)
sprite_image.save("walk_frame0.png")

# 3. Adjust animation speed for translated dialogue timing
for frame in first_seq.frames:
    frame.delay = 6  # 6/60th second per frame

open("anim_mod.nanr", "wb").write(nanr.to_bytes())
print("Exported rendered frame and updated animation timing.")
```

---

## Recipe 10: Nintendo DS Streaming Audio & Sound Wave Archive Localization

Extract voice clips from `.strm` containers, convert them to standard WAV for translation or subtitling, and repack modified WAV audio back into `.strm` and `.swar` archives.

```python
from miorom.platforms.nds.strm import STRMFile
from miorom.platforms.nds.swar import SWARFile

# 1. Decode cutscene STRM audio directly to WAV
strm = STRMFile(open("cutscene_voice.strm", "rb").read())
print(f"Sample Rate: {strm.sample_rate} Hz, Channels: {strm.channels}")
open("cutscene_voice.wav", "wb").write(strm.to_wav())

# 2. Encode localized WAV audio into standard IMA-ADPCM STRM
with open("cutscene_voice_id.wav", "rb") as f:
    localized_wav = f.read()
new_strm = STRMFile.from_wav(localized_wav, wave_type=2)
open("cutscene_voice_id.strm", "wb").write(new_strm.to_bytes())

# 3. Extract and re-inject sound wave effects from SWAR
swar = SWARFile(open("sfx.swar", "rb").read())
swar.extract_all("extracted_sfx/")
# ... replace any sfx in extracted_sfx/ ...
swar.pack_from_directory("extracted_sfx/", "sfx_localized.swar")
print("Successfully localized streaming and sound wave archives.")
```

---

## Recipe 11: PlayStation 1 Memory Card Inspection & Animated Save Icon Extraction

Inspect PS1 128KB memory card images (`.mcr`, `.mcd`, `.sav`), extract Shift-JIS game titles, and export 16x16 4bpp animated icon frames to PNG.

```python
from miorom.platforms.psx.memory_card import PSXMemoryCard

# 1. Load 128 KB memory card
card = PSXMemoryCard.from_file("memcard.mcr")
print(f"Available free blocks: {card.free_blocks}/15")

# 2. Iterate through all saves on card
for save in card.saves:
    print(f"[{save.product_code}] {save.title} - Size: {save.block_count} block(s)")
    
    # 3. Export animated icon frames
    for frame_idx, icon_img in enumerate(save.icons):
        icon_img.save(f"{save.product_code}_frame{frame_idx}.png")

# 4. Update save game title
if card.saves:
    card.saves[0].title = "Final Fantasy VII (Terjemahan ID)"
    card.save("memcard_updated.mcr")
print("Memory card inspection and title update completed.")
```

