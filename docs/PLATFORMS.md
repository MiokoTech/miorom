# MioROM Platform & Console Format Reference

MioROM includes native parsers, serializers, and filesystem managers for multiple console generations. This reference details the platform-specific modules, file formats, and memory architectures supported by the framework.

---

## Supported Platform Matrix

| Module | Architecture | Supported Formats & Containers |
| :--- | :--- | :--- |
| `miorom.platforms.nds` | ARM7TDMI / ARM946E-S | `.nds` ROM, NARC (`.narc`), NFTR Font (`.nftr`), SDAT Audio (`.sdat`) |
| `miorom.platforms.wii` | PowerPC Broadway / Hollywood | U8 Archive (`.arc`, `.szs`), TPL Textures (`.tpl`), BRFNT Font (`.brfnt`) |
| `miorom.platforms.gc` | PowerPC Gekko / Flipper | Disc Images (`.iso`, `.gcm`), FST Filesystem (`FstInjector`), DOL Executable |
| `miorom.platforms.psx` | MIPS R3000A | ISO9660 Disc, CUE/BIN Multi-track, PS-X EXE, TIM Images, STR Movie, CD-XA |
| `miorom.platforms.n64` | MIPS VR4300 | `.z64` (BE), `.v64` (Swapped), `.n64` (LE), IPL3 CIC Checksums |
| `miorom.platforms.gba` | ARM7TDMI | `.gba` Cartridge, Save Chip Detector (EEPROM/SRAM/Flash), Complement CRC |
| `miorom.platforms.gb` | Sharp LR35902 (Z80-like) | `.gb`, `.gbc`, MBC1/2/3/5 Bank Addressing, Header & Global Checksums |
| `miorom.platforms.snes` | Ricoh 5A22 (W65C816S) | LoROM, HiROM, ExHiROM Mapping, 512-byte SMC Stripper, Complement Checksum |
| `miorom.platforms.md` | Motorola 68000 / Z80 | `.bin`, `.md`, SMD Interleaved (`.smd`), 16-bit Big-Endian Checksum |

---

## 1. Nintendo DS (`miorom.platforms.nds`)

### ROM Structure (`NDSRom`)
Parses official Nintendo DS cartridge images:
- Reads 512-byte header (Game title, game code, maker code, ARM9/ARM7 load addresses and offsets).
- Extracts and re-injects ARM9 (`arm9.bin`) and ARM7 (`arm7.bin`) executables.
- Parses File Allocation Table (FAT) and File Name Table (FNT).
- Extracts multilingual banner icons and titles (Japanese, English, French, German, Italian, Spanish).

```python
from miorom.platforms.nds import NDSRom

rom = NDSRom.from_file("game.nds")
print(f"Title: {rom.title}, Code: {rom.game_code}")
print("English Title:", rom.get_banner_title(language=1))

arm9_bytes = rom.get_arm9_binary()
# Modify ARM9 binary...
rom.set_arm9_binary(modified_arm9_bytes)
rom.save("game_repacked.nds")
```

### NARC Container (`NARCArchive`)
Full parser and builder for official Nintendo DS `.narc` file archives, maintaining 4-byte chunk alignments across `BTAF` (allocation table), `BTNF` (name table), and `GMIF` (file data).

```python
from miorom.platforms.nds import NARCArchive

# Unpack all subfiles
NARCArchive.extract_all("messages.narc", "extracted_messages/")

# Rebuild archive
NARCArchive.pack("extracted_messages/", "messages_repacked.narc")
```

### Nitro Font Editor (`NFTRFont`)
Parser and serializer for Nintendo DS `.nftr` binary fonts (`FNTH`, `CWDH`, `CMAP`, `PLGC` chunks), allowing custom glyph insertion and kerning modifications:

```python
from miorom.platforms.nds import NFTRFont
from miorom.graphics import Tile

font = NFTRFont.from_bytes(open("font.nftr", "rb").read())
print(f"Height: {font.height}px, BPP: {font.bpp}")

# Add custom accented letter or symbol
custom_glyph_tile = Tile([1 if (x + y) % 2 == 0 else 0 for y in range(8) for x in range(8)])
font.set_glyph("É", custom_glyph_tile, advance=7)

with open("font_edited.nftr", "wb") as f:
    f.write(font.to_bytes())
```

---

## 2. Nintendo Wii & GameCube (`miorom.platforms.wii`, `miorom.platforms.gc`)

### U8 Archive (`U8Archive`)
Extracts and reconstructs Nintendo `.arc` and `.szs` archives with standard 32-byte alignment:

```python
from miorom.platforms.wii import U8Archive

U8Archive.extract_all("Layout.arc", "Layout_extracted/")
U8Archive.pack("Layout_extracted/", "Layout_repacked.arc")
```

### TPL Texture Converter (`TPLFile`)
Inspects and decodes GameCube and Wii texture banks:
- Supported formats: CMPR (DXT1 compressed), RGB5A3, RGB565, RGBA8, I4, I8, IA4, IA8.
- Decodes directly to raw 32-bit RGBA pixel buffers.

```python
from miorom.platforms.wii import TPLFile

tpl = TPLFile.from_file("textures.tpl")
rgba_data = tpl.decode_rgba(image_index=0)
```

### Binary Revolution Font (`BRFNTFont`)
Reads official Wii BRFNT font metrics, character maps, and proportional glyph widths for Variable-Width Font dialogue measurement:

```python
from miorom.platforms.wii import BRFNTFont

font = BRFNTFont.from_file("rodin.brfnt")
pixel_width = font.get_text_width("Good morning, adventurer!")
is_valid, missing = font.audit_string("Hello World! (é)")
```

### Disc Image & FST File Injection (`FstInjector`)
Modifies GameCube and Wii File System Tables (FST) in-place inside `.iso` or `.gcm` files without requiring external toolchains (`wit`, `gcit`):

```python
from miorom.platforms.gc import FstInjector

injector = FstInjector("game.iso")
print(injector.list_files())

# Replace binary subfile in-place
injector.replace_file("DATA/files/script/event01.bin", modified_event_bytes)
injector.save("game_patched.iso")
```

### Live Dolphin Memory Bridge (`DolphinClient`)
Connects directly to a running instance of Dolphin Emulator via shared memory (`/dev/shm/dolphin-emu`) or GDB Remote Serial Protocol:

```python
from miorom.debug import DolphinClient

client = DolphinClient()
if client.connect():
    # Read live dialogue buffer from virtual RAM
    dialogue = client.read_string(0x80540000, max_len=128, encoding="utf-16-be")
    
    # Write live text in real-time
    client.write_string(0x80540000, "Live Translation Test", encoding="utf-16-be")
```

---

## 3. PlayStation 1 (`miorom.platforms.psx`, `miorom.platforms.cdrom`, `miorom.platforms.iso`)

### Optical Disc Images (`ISO9660` & `CueBinDisc`)
- **`ISO9660`**: Pure-Python ISO reader and file injector. Replaces files in-place and automatically handles LBA sector expansion when file sizes increase.
- **`CueBinDisc`**: Parses CDRWIN `.cue` sheets and multi-track `.bin` disc images. Reads raw 2352-byte sectors, extracts 2048-byte Mode 1 / Mode 2 Form 1 data tracks, and recalculates ECMA-130 EDC checksums.

```python
from miorom.platforms.iso import ISO9660

iso = ISO9660.from_file("game.iso")
file_bytes = iso.read_file("SYSTEM/TEXT.DAT")

# Replace file (auto-relocates sectors if larger)
iso.replace_file("SYSTEM/TEXT.DAT", modified_bytes)
with open("game_patched.iso", "wb") as f:
    f.write(iso.to_bytes())
```

### PS-X Executables (`PSXExe`)
Parses and rebuilds the 2048-byte PS-X EXE header:
- Initial Program Counter (`initial_pc`).
- Initial Stack Pointer (`initial_sp`) and Global Pointer (`initial_gp`).
- Text RAM load address and binary section sizes.

```python
from miorom.platforms.psx import PSXExe

exe = PSXExe.from_file("SLUS_000.01")
print(f"Entrypoint: 0x{exe.initial_pc:08X}, Load Address: 0x{exe.text_ram_address:08X}")
```

### TIM Textures (`TIMImage`)
Parses, modifies, and serializes PS1 `.tim` texture files:
- 4bpp and 8bpp color indexed with CLUT palette.
- 16bpp and 24bpp direct color modes.

```python
from miorom.platforms.psx import TIMImage

tim = TIMImage(open("sprite.tim", "rb").read())
print(f"Dimensions: {tim.width}x{tim.height}, BPP: {tim.bpp}")
```

### Video & Audio Demuxing (`StrDemuxer`, `CdXaDecoder`)
- **`StrDemuxer`**: Demuxes raw CD sector streams (`.str`) into MDEC macroblock video bitstreams and synchronized audio channels.
- **`CdXaDecoder`**: Decodes CD-ROM XA Mode 2 Form 2 ADPCM audio sectors into 16-bit PCM WAV audio.

```python
from miorom.platforms.psx import StrDemuxer
from miorom.audio import CdXaDecoder

demuxer = StrDemuxer(open("opening.str", "rb").read())
frames = demuxer.demux_video_frames()
audio_wav = demuxer.demux_audio(channel=1)

with open("opening_audio.wav", "wb") as f:
    f.write(audio_wav)
```

---

## 4. Nintendo 64 (`miorom.platforms.n64`)

### Endianness Normalization (`N64Rom`, `N64ByteOrder`)
Normalizes and converts between the three common N64 ROM file layouts:
- Big-Endian (`.z64`, standard cartridge byte order: `0x80371240`).
- Byte-Swapped (`.v64`, CD64 / Doctor V64 copier order: `0x37804012`).
- Little-Endian (`.n64`, Tristar 64 copier order: `0x40123780`).

```python
from miorom.platforms.n64 import N64Rom, N64ByteOrder

rom = N64Rom.from_file("game.v64")
print(f"Game: {rom.header.title}, CIC: {rom.cic}")

# Save in standard Big-Endian format
rom.save("game_standard.z64", target_order=N64ByteOrder.BIG_ENDIAN)
```

### Bootloader Checksum Recalculation (`fix_n64_checksum`)
Recalculates the exact 64-bit IPL3 boot checksum stored at offsets `0x10` and `0x14` for all retail CIC chip models:
- CIC-6101 / 7102 (Star Fox 64)
- CIC-6102 / 7101 (Super Mario 64, Ocarina of Time, retail standard)
- CIC-6103 / 7103 (Paper Mario, Banjo-Tooie)
- CIC-6105 / 7105 (Zelda: Majora's Mask, Diddy Kong Racing)
- CIC-6106 / 7106 (F-Zero X)
- CIC-5101 (Aleck64 arcade)

```python
from miorom.platforms.n64 import fix_n64_checksum

rom_bytes = bytearray(open("mario64.z64", "rb").read())
# Modify game data...
fixed_bytes = fix_n64_checksum(rom_bytes, cic="6102")
```

---

## 5. Game Boy Advance (`miorom.platforms.gba`)

### Cartridge Header & Save Type Detection (`GBARom`)
- Validates 192-byte header, 12-character game title, 4-character game code, and 96-byte Nintendo logo bitmap.
- Recalculates header complement check byte at offset `0xBD`.
- Automatically scans ROM for backup save chip driver signatures:
  - SRAM (32KB)
  - EEPROM (4KB / 64KB)
  - Flash (512KB / 1MB)

```python
from miorom.platforms.gba import GBARom

gba = GBARom.from_file("pokemon_emerald.gba")
print(f"Title: {gba.title}, Code: {gba.game_code}")
print("Save Hardware Type:", gba.detect_save_type())

# Recalculate checksum after header edits
gba.fix_header_checksum()
```

---

## 6. Game Boy & Game Boy Color (`miorom.platforms.gb`)

### Bank Address Resolution & Checksum Repair (`GBRom`)
- Translates banked cartridge offsets: `resolve_bank_address(bank, addr)`.
- Verifies 48-byte scrolling logo.
- Recalculates 8-bit header complement checksum (`offset 0x14D`) and 16-bit global cartridge checksum (`offset 0x14E`).

```python
from miorom.platforms.gb import GBRom

gb = GBRom.from_file("zelda.gbc")
file_offset = gb.resolve_bank_address(bank=2, addr=0x4000)

gb.fix_header_checksum()
gb.fix_global_checksum()
gb.save("zelda_fixed.gbc")
```

---

## 7. Super Nintendo (`miorom.platforms.snes`)

### Memory Mapping & SMC Copier Header Management (`SNESRom`)
- Detects memory mapping models: LoROM (`$00:$8000`), HiROM (`$C0:$0000`), and ExHiROM.
- Detects and strips 512-byte SMC/SWC copier backup headers to produce clean `.sfc` images.
- Recalculates the internal 16-bit checksum and inverted complement checksum in the SNES registration block.

```python
from miorom.platforms.snes import SNESRom

snes = SNESRom.from_file("chrono_trigger.smc")
print("Mapping Model:", snes.mapping_type)

# Clean copier header and recalculate checksum
snes.strip_smc_header()
snes.fix_checksum()
snes.save("chrono_trigger_clean.sfc")
```

---

## 8. Sega Genesis / Mega Drive (`miorom.platforms.md`)

### Format De-interleaving & Checksum Repair (`MDRom`)
- Detects and de-interleaves Super Magic Drive (`.smd`) interleaved block images into standard linear flat binaries (`.bin`/`.md`).
- Parses 512-byte header at offset `0x0100` (Domestic title, Overseas title, Serial number, I/O support, SRAM memory bounds).
- Recalculates the 16-bit big-endian checksum stored at offset `0x018E`.

```python
from miorom.platforms.md import MDRom

md = MDRom.from_file("sonic.smd")
if md.is_smd:
    md.deinterleave() # Convert to standard linear binary

md.fix_checksum()
md.save("sonic_clean.bin")
```
