# MioROM Platform & Console Format Reference

MioROM includes native parsers, serializers, and filesystem managers for multiple console generations. This reference details the platform-specific modules, file formats, and memory architectures supported by the framework.

---

## Supported Platform Matrix

| Module | Architecture | Supported Formats & Containers |
| :--- | :--- | :--- |
| `miorom.platforms.nds` | ARM7TDMI / ARM946E-S / Thumb | `.nds` ROM, NARC (`.narc`), NFTR Font, NCLR/NCGR/NSCR Graphics, SDAT Audio |
| `miorom.platforms.wii` | PowerPC Broadway / Hollywood | U8 Archive (`.arc`, `.szs`), TPL Textures (`.tpl`), BRFNT Font, DSP-ADPCM Audio |
| `miorom.platforms.gc` | PowerPC Gekko / Flipper | Disc Images (`.iso`, `.gcm`), FST Filesystem (`FstInjector`), DOL Executable |
| `miorom.platforms.psx` | MIPS R3000A | ISO9660 Disc, CUE/BIN Multi-track, PS-X EXE, TIM Images, VAG SPU-ADPCM, STR Movie, CD-XA |
| `miorom.platforms.n64` | MIPS VR4300 | `.z64` (BE), `.v64` (Swapped), `.n64` (LE), IPL3 CIC Checksums, Fast3D Textures |
| `miorom.platforms.gba` | ARM7TDMI / Thumb | `.gba` Cartridge, Save Chip Detector, BIOS SWI Resolver (`GBASwiResolver`), Multiboot (`.mb`) Builder |
| `miorom.platforms.gb` | Sharp LR35902 (Z80-like) | `.gb`, `.gbc`, MBC1/2/3/5 Bank Addressing, Header & Global Checksums |
| `miorom.platforms.snes` | Ricoh 5A22 (W65C816S) | LoROM, HiROM, ExHiROM Mapping, 512-byte SMC Stripper, SPC700 BRR Audio, Complement Checksum |
| `miorom.platforms.nes` | MOS Technology 6502 | `.nes`, `.unf`, iNES, NES 2.0, Mapper Identification, PRG/CHR Separation |
| `miorom.platforms.md` | Motorola 68000 / Z80 | `.bin`, `.md`, SMD Interleaved (`.smd`), 16-bit Big-Endian Checksum |
| `miorom.platforms.sega_disc` | Hitachi SH-2 / SH-4 | Sega Saturn 512B Security Sector, Dreamcast IP.BIN / GD-ROM GDI Sheets |
| `miorom.platforms.psp` | MIPS R4000 (Allegrex) | EBOOT.PBP, PARAM.SFO (System File Object), PS1 Classics & Homebrew |
| `miorom.platforms.iso` | Universal Optical Media | ISO 9660 Disc Synthesizer (`Iso9660Builder`), Compressed ISO (`CSOImage`) |

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

### 2D Graphics Suite (`NCLRFile`, `NCGRFile`, `NSCRFile`)
Full pure-Python suite for extracting, modifying, and repacking 2D graphics in Nintendo DS games:
- **`NCLRFile`**: Nitro Color Palette (`.nclr`) reader and serializer for BGR555 color palettes.
- **`NCGRFile`**: Nitro Character Graphic (`.ncgr`) reader and serializer for 4bpp/8bpp tiled character graphics.
- **`NSCRFile`**: Nitro Screen Resource (`.nscr`) background tilemap screen reader with flip/palette attribute support.

```python
from miorom.platforms.nds import NCLRFile, NCGRFile, NSCRFile

# Load palette, character tiles, and screen map
nclr = NCLRFile.from_bytes(open("bg.nclr", "rb").read())
ncgr = NCGRFile.from_bytes(open("bg.ncgr", "rb").read())
nscr = NSCRFile.from_bytes(open("bg.nscr", "rb").read())

# Access and modify palette colors
print("Colors in palette:", len(nclr.colors))
nclr.colors[0] = (255, 0, 0)  # Red RGB

# Export modified files
open("bg_mod.nclr", "wb").write(nclr.to_bytes())
open("bg_mod.ncgr", "wb").write(ncgr.to_bytes())
open("bg_mod.nscr", "wb").write(nscr.to_bytes())
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

---

## 9. Nintendo Entertainment System (`miorom.platforms.nes`)

### Cartridge Header Parsing & Mapper Identification (`NESRom`)
- Parses 16-byte iNES and modern NES 2.0 headers (`NESHeaderStruct`).
- Identifies memory mappers (NROM, MMC1, MMC3, MMC5, UNROM, CNROM, etc.).
- Detects vertical, horizontal, and four-screen mirroring modes.
- Separates PRG ROM (program code) and CHR ROM/RAM (pattern graphics).
- Extracts and strips 512-byte trainer buffers if present.

```python
from miorom.platforms.nes import NESRom

rom = NESRom.from_file("mario.nes")
print(f"Mapper: {rom.mapper_id}, PRG Size: {len(rom.prg_rom)} bytes, CHR Size: {len(rom.chr_rom)} bytes")
print("Is NES 2.0 format:", rom.is_nes20)

# Modify PRG or CHR data and repack
rom.save("mario_mod.nes")
```

---

## 10. Console Audio & Sound Codecs (`miorom.audio`)

MioROM features native pure-Python codecs for retro audio processing and extraction:

### Sony PS1 & PS2 SPU-ADPCM (`VAGFile`, `VAGCodec`)
Standard audio format used for character voices, dialogue, and sound effects across PlayStation 1 and 2 games.
- Decodes 16-byte blocks (28 samples per block) into 16-bit PCM using Sony predictor filter coefficients.
- Encodes PCM audio into SPU-ADPCM blocks with optimal filter selection.
- Directly exports to standard 16-bit RIFF/WAVE (`.wav`) files.

```python
from miorom.audio.vag import VAGFile

vag = VAGFile.from_bytes(open("voice.vag", "rb").read())
print(f"Sample Rate: {vag.header.sample_rate} Hz, Name: {vag.header.name}")

# Export decoded audio directly to WAV
open("voice.wav", "wb").write(vag.to_wav())

# Encode raw PCM into a new VAG file
new_vag = VAGFile.from_pcm(samples=[...], sample_rate=44100, name="DIALOGUE_01")
open("new_voice.vag", "wb").write(new_vag.to_bytes())
```

### Super Nintendo SPC700 BRR (`BRRCodec`)
Bit Rate Reduction (BRR) audio format utilized by the SNES S-DSP sound processor for all instruments and sound effects:
- Decodes 9-byte BRR blocks (16 samples per block) with 4-filter Gaussian interpolation.
- Encodes 16-bit PCM into BRR blocks with loop point tagging.
- Wraps decoded audio into WAV files.

```python
from miorom.audio.brr import BRRCodec

# Decode raw SNES BRR data to PCM samples
samples = BRRCodec.decode(open("sample.brr", "rb").read())

# Export to WAV
wav_bytes = BRRCodec.to_wav(open("sample.brr", "rb").read(), sample_rate=32000)
open("sample.wav", "wb").write(wav_bytes)

# Encode PCM samples to BRR
brr_data = BRRCodec.encode(samples, loop_point=16)
open("sample_repacked.brr", "wb").write(brr_data)
```

### Nintendo GameCube & Wii DSP-ADPCM (`DSPADPCMCodec`)
Standard audio codec for `.dsp` and `.brstm` streams on GameCube and Wii:
- Decodes 8-byte frames (14 samples per frame) using hardware coefficient matrix.
- Generates 16-bit PCM WAV audio.

```python
from miorom.audio.dsp_adpcm import DSPADPCMCodec

dsp_data = open("bgm.dsp", "rb").read()
pcm_samples = DSPADPCMCodec.decode(dsp_data)
open("bgm.wav", "wb").write(DSPADPCMCodec.to_wav(dsp_data, sample_rate=32000))
```

---

## 11. PlayStation Portable (`miorom.platforms.psp`)

### PARAM.SFO Metadata (`SFOFile`)
Parser and builder for Sony's standard System File Object configuration file used across PSP, PS3, PS4, and PS Vita:
- Reads and writes UTF-8 strings, ASCII strings, and 32-bit unsigned integers.
- Property accessors for `title`, `disc_id`, and `category`.

```python
from miorom.platforms.psp import SFOFile

sfo = SFOFile.from_file("PARAM.SFO")
print(f"Title: {sfo.title}, Disc ID: {sfo.disc_id}, Category: {sfo.category}")

# Update metadata
sfo["TITLE"] = "Final Fantasy Tactics (Custom Translation)"
sfo.save("PARAM.SFO")
```

### EBOOT.PBP Container (`PBPFile`)
Container archive unpacker and synthesizer for PSP homebrew, updates, and PS1 Classics packages:
- Access and modify all 8 canonical PBP sections: `PARAM.SFO`, `ICON0.PNG`, `ICON1.PMF`, `PIC0.PNG`, `PIC1.PNG`, `SND0.AT3`, `DATA.PSP`, `DATA.PSAR`.
- Direct `.sfo` parsed object property.
- Bulk directory extraction via `extract_all()`.

```python
from miorom.platforms.psp import PBPFile

pbp = PBPFile.from_file("EBOOT.PBP")
print(f"Game: {pbp.sfo.title if pbp.sfo else 'Unknown'}")

# Extract all sections to directory
pbp.extract_all("extracted_pbp/")

# Modify executable or assets and repack
pbp.set_section("ICON0.PNG", open("new_icon.png", "rb").read())
pbp.save("EBOOT_MODIFIED.PBP")
```

---

## 12. Optical Disc & Compressed ISO (`miorom.platforms.iso`)

### Compressed ISO (`CSOImage`)
Sector-based random-access reader and compressor for CSO/CISO disc images used by PSP and PS2 emulators:
- Transparent zlib/deflate decompression per sector.
- Random-access multi-sector and cross-boundary byte reads (`read_bytes()`).
- Direct decompression streaming to disk (`decompress_to_file()`).
- Pure-Python ISO-to-CSO compressor (`CSOImage.compress_iso()`).

```python
from miorom.platforms.iso import CSOImage

# Open CSO image for random-access reading
with CSOImage("game.cso") as cso:
    print(f"Total Sectors: {cso.sector_count}, Block Size: {cso.sector_size}")
    boot_sector = cso.read_sector(16)
    slice_data = cso.read_bytes(0x8000, 1024)

# Compress raw ISO to CSO format
CSOImage.compress_iso("game.iso", output_path="game.cso", block_size=2048)
```

---

## 13. Sega Optical Discs (`miorom.platforms.sega_disc`)

### Saturn Disc Security Sector (`SaturnDiscHeader`)
Parser and editor for Sega Saturn 512-byte bootstrap security sectors (Sector 0):
- Verifies `SEGA SEGASATURN ` magic, product numbers, release dates, and boot filenames (`0.BIN`).
- Modifies and unlocks area symbols with `make_region_free()` (`JTUEKABL`).

```python
from miorom.platforms.sega_disc import SaturnDiscHeader

hdr = SaturnDiscHeader.from_file("saturn_game.iso")
print(f"Title: {hdr.title}, Version: {hdr.version}, Boot File: {hdr.boot_file}")
print("Region Free:", hdr.is_region_free)

hdr.make_region_free()
```

### Dreamcast Bootstrap & GDI Descriptors (`DreamcastIpBin`, `GDISheet`)
Handles Dreamcast initial bootstrap sector 0 (IP.BIN) and GD-ROM `.gdi` multi-track sheets:
- Recalculates 16-bit CRC checksums across IP.BIN headers via `calculate_crc()`.
- Unlocks worldwide region code (`JUE`).
- Inspects and parses GDI multi-track sheets, identifying high-density game data tracks.

```python
from miorom.platforms.sega_disc import DreamcastIpBin, GDISheet

# Parse Dreamcast IP.BIN
ip = DreamcastIpBin.from_file("IP.BIN")
ip.make_region_free()
ip.crc = ip.calculate_crc()

# Parse GDI descriptor sheet
gdi = GDISheet.from_file("disc.gdi")
hd_track = gdi.high_density_track
print(f"High Density Track: {hd_track.track_number} ({hd_track.filename}) at LBA {hd_track.start_lba}")
```

---

## 14. Game Boy Advance Extended (`miorom.platforms.gba`)

### BIOS SWI Symbolic Resolver (`GBASwiResolver`)
Resolves and annotates official Nintendo GBA BIOS system calls across ARM and Thumb disassemblies:
- 32-entry lookup database covering math, decompression (LZ77, Huffman, RL), sound (MusicPlayer2000), and DMA routines.
- Instruction annotation (`annotate_thumb_instruction`, `annotate_arm_instruction`).
- Binary scanner (`scan_swi_calls`).

```python
from miorom.platforms.gba import GBASwiResolver

# Scan binary payload for BIOS SWI calls
calls = GBASwiResolver.scan_swi_calls(arm_code, thumb_mode=True, base_addr=0x08000000)
for call in calls:
    print(f"At {hex(call['address'])}: {call['name']} - {call['description']}")
```

### Multiboot Payload Builder (`GBAMultiboot`)
Generates valid GBA Multiboot (`.mb`) 256KB EWRAM executables for cable transmission:
- Synthesizes ARM entry branch, official Nintendo logo, metadata, and complement checksums.
- Validates and parses `.mb` files.

```python
from miorom.platforms.gba import GBAMultiboot

mb_data = GBAMultiboot.create_payload(
    code_bytes=my_ewram_code,
    title="MINIGAME",
    game_code="MB01",
)
with open("game.mb", "wb") as f:
    f.write(mb_data)
```


