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

### Nitro 3D Model Engine (`NSBMDFile`, `NSBTXFile`)
Full parser, model inspector, and bidirectional texture extractor/injector for official Nintendo DS 3D models (`.nsbmd` / `BMD0` and `MDL0`):
- **Model Hierarchy**: Parses bone nodes, model dictionaries, and material definitions (`NSBMDModel`, `NSBMDMaterial`).
- **Standalone Texture Bridge**: Exports embedded `TEX0` sections to standalone `.nsbtx` files via `export_nsbtx()`, and injects translated/custom textures via `import_nsbtx()`.
- **Texture Replacement**: Replaces individual texture images in-place without disturbing 3D display list bytecode.
- **Single-Block Stripping**: Converts 2-block containers into single-block `MDL0`-only models (`strip_textures()`).

```python
from miorom.platforms.nds import NSBMDFile, NSBTXFile

nsbmd = NSBMDFile.from_file("character.nsbmd")
print(f"Models: {len(nsbmd.models)}, Materials: {len(nsbmd.models[0].materials)}")

# Export embedded textures to .nsbtx
nsbtx = nsbmd.export_nsbtx()
nsbtx.save("character_textures.nsbtx")

# Inject modified texture bank back into 3D model container
nsbmd.import_nsbtx(nsbtx)
nsbmd.save("character_translated.nsbmd")
```

### Cartridge Banner Engine (`NDSBanner`)
Comprehensive parser, editor, and builder for official Nintendo DS cartridge banner icons and multilingual titles:
- Supports Banner versions 1 (Original NDS), 2, 3 (iQue / Animated frames), and Version 0x0103 (DSi animated icons).
- Manages 16-color 4bpp icon tilemaps, animated sequence frames, CRC16 verification, and 8 language titles (Japanese, English, French, German, Italian, Spanish, Chinese, Korean).

```python
from miorom.platforms.nds import NDSBanner

banner = NDSBanner.from_bytes(open("banner.bin", "rb").read())
print("English Title:", banner.get_title("english"))

# Update localized title and fix banner CRC checksums
banner.set_title("english", "Custom Translation v1.0")
banner.fix_checksums()
open("banner_edited.bin", "wb").write(banner.to_bytes())
```

### ARM9 Backward Compression (`BLZ`)
Pure-Python compressor and decompressor for Nintendo DS Bottom-BLZ (`blz`) ARM9 payloads:
- Decompresses reverse LZSS payloads stored at the end of ARM9 executables without native binaries (`arm-none-eabi`).

```python
from miorom.compression.blz import BLZ

decompressed_arm9 = BLZ.decompress(compressed_arm9_payload)
recompressed_payload = BLZ.compress(decompressed_arm9)
```

### 2D Sprite Cells & OAM Bank (`NCERFile`, `NCERCell`)
Comprehensive parser, builder, and sprite cell assembler for official Nintendo DS `.ncer` binary files:
- Traverses multi-cell character definitions across OAM shapes (Square, Wide, Tall) and sizes (0..3, 8x8 up to 64x64 pixels).
- Configures tile offsets, palette bank indices, horizontal/vertical flipping, priority bits, and mosaic modes.
- Assembles multiple OAM cells with `NCGRFile` tiles and `NCLRFile` palettes into composited PIL images via `render_cell()`.

```python
from miorom.platforms.nds import NCERFile, NCGRFile, NCLRFile

ncer = NCERFile.from_bytes(open("character.ncer", "rb").read())
ncgr = NCGRFile.from_bytes(open("character.ncgr", "rb").read())
nclr = NCLRFile.from_bytes(open("character.nclr", "rb").read())

# Inspect cells in cell bank
print(f"Total Banks: {len(ncer.banks)}, Cells in Bank 0: {len(ncer.banks[0].cells)}")

# Render composite sprite image to PIL
sprite_image = ncer.render_cell(bank_index=0, ncgr=ncgr, nclr=nclr)
sprite_image.save("character_sprite.png")
```

### 2D Animation Sequences (`NANRFile`, `NANRSequence`, `NANRFrame`)
Keyframe animation sequencer and timeline editor for Nintendo DS `.nanr` sprite animations:
- Manages animation sequences (`NANRSequence`) and frame timing (`NANRFrame`) measured in 1/60s hardware ticks.
- Supports all official playback modes: forward once, forward loop, reverse once, and reverse loop.
- Links sequence keyframes directly to `NCERFile` cell bank indices.

```python
from miorom.platforms.nds import NANRFile

nanr = NANRFile.from_bytes(open("walk_anim.nanr", "rb").read())
print(f"Animation Sequences: {len(nanr.sequences)}")

for seq in nanr.sequences:
    print(f"Sequence Mode: {seq.play_mode}, Frame Count: {len(seq.frames)}")

# Modify frame delay timing
nanr.sequences[0].frames[0].delay = 8  # 8/60 second
open("walk_anim_mod.nanr", "wb").write(nanr.to_bytes())
```

### ARM Overlay Table Manager (`NDSOverlayTable`, `NDSOverlayManager`, `NDSOverlayCompressor`)
Full manager and address relocator for Nintendo DS ARM9 (`y9.bin`) and ARM7 (`y7.bin`) overlay memory mappings:
- Reads and updates 32-byte overlay records (`NDSOverlayEntry`): RAM start address, RAM allocated size, BSS reservation, and FAT file ID.
- Automatically handles Nintendo LZ10 compressed overlays (`NDSOverlayCompressor`).
- High-level `NDSOverlayManager` extracts, replaces, and automatically expands cartridge boundaries when translated overlays grow.

```python
from miorom.platforms.nds import NDSRom
from miorom.platforms.nds.overlay import NDSOverlayManager

rom = NDSRom.from_file("game.nds")
mgr = NDSOverlayManager(rom)

# Extract and inspect ARM9 overlay 12
overlay_bytes = mgr.extract_overlay(overlay_id=12, arm="arm9")

# Replace overlay with modified code/data (auto-relocates and recompresses if needed)
report = mgr.replace_overlay(overlay_id=12, data=modified_overlay_bytes, arm="arm9", compress=True)
print(f"Overlay {report.overlay_id}: New RAM Size = {report.new_ram_size} bytes")
rom.save("game_overlay_patched.nds")
```

### Nitro Streaming Audio (`STRMFile`)
Nintendo DS Nitro Stream (`.strm`) multi-channel streaming audio container parser, decoder, and builder:
- Decodes multi-channel cutscene voice acting, jingles, and BGM to standard 16-bit RIFF/WAVE (`.wav`).
- Supports PCM8, PCM16, and 4-bit IMA-ADPCM waveforms with hardware timer periods and loop blocks.
- Encodes standard WAV files back into clean `.strm` containers.

```python
from miorom.platforms.nds.strm import STRMFile

strm = STRMFile(open("voice.strm", "rb").read())
print(f"Sample Rate: {strm.sample_rate} Hz, Channels: {strm.channels}, Looped: {strm.is_looped}")

# Export decoded audio directly to WAV
open("voice.wav", "wb").write(strm.to_wav())

# Rebuild STRM from WAV
new_strm = STRMFile.from_wav(open("new_voice.wav", "rb").read(), wave_type=2)  # IMA-ADPCM
open("new_voice.strm", "wb").write(new_strm.to_bytes())
```

### Sound Wave Archive & Audio Ripper (`SWARFile`, `SWAVEntry`)
Parser and rebuilder for Nintendo DS Sound Wave Archives (`.swar`) containing SWAV instrument and sound effect samples:
- Extracts embedded sound waveforms to individual 16-bit WAV files while preserving loop points and sample rates.
- Re-injects localized or remastered audio samples and serializes compliant `.swar` archives.

```python
from miorom.platforms.nds.swar import SWARFile

swar = SWARFile(open("sound_data.swar", "rb").read())
print(f"Waveform Samples: {len(swar.entries)}")

# Extract all sound effects to WAV directory
swar.extract_all("extracted_sfx/")

# Rebuild SWAR archive from WAV directory
swar.pack_from_directory("extracted_sfx/", "sound_data_repacked.swar")
```

### Nitro 2D Scene Graph & Asset Catalog (`NitroAssetCatalog`, `NitroSceneGraph`)
Forensic scanner and scene compositor cross-linking the entire 2D graphics suite:
- Automatically indexes and pairs matching `.ncgr`, `.nclr`, `.nscr`, `.ncer`, and `.nanr` binaries from ROM directory trees.
- Validates structural palette constraints and tile layout bounds.
- Renders full animated scenes to multi-frame GIF or PNG image sheets.

```python
from miorom.platforms.nds.asset_graph import NitroAssetCatalog, NitroSceneGraph

catalog = NitroAssetCatalog("extracted_fs/ui/")
catalog.scan(recursive=True)

scene = NitroSceneGraph.from_catalog(catalog, scene_name="title_screen")
rendered_image = scene.render_composite()
rendered_image.save("title_screen_composite.png")
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

### RVZ Compressed Optical Disc (`RVZImage`, `RVZBuilder`)
Parses, unpacks, and synthesizes Dolphin RVZ compressed disc images across version 0, 1, and 2:
- Supports packed chunk decompression with hash tables, and reconstruction of clean raw ISO images.

```python
from miorom.platforms.iso.rvz import RVZImage

rvz = RVZImage.from_file("mario_galaxy.rvz")
print(f"Game ID: {rvz.game_id}, Version: {rvz.version}")
iso_bytes = rvz.decompress_to_iso()
```

### Disc Channel Banner (`WiiBanner`, `GCBanner`)
Parses and updates GameCube and Wii channel banner files (`opening.bnr`):
- Modifies BNR1 / BNR2 titles and descriptions in English, French, German, Italian, Spanish, and Japanese.
- Extracts and serializes RGB5A3 and RGB565 banner graphic textures.

```python
from miorom.platforms.wii.banner import WiiBanner

bnr = WiiBanner.from_file("opening.bnr")
print("Title:", bnr.get_title(0))
bnr.set_title(0, "Custom Translated Game")
bnr.save("opening_edited.bnr")
```

### Binary Revolution Layout Animation & Screen (`BRLANFile`, `BRLYTFile`)
Full UI localization suite for Nintendo Wii and 3DS layout archives (`.brlyt`, `.brlan`):
- **`BRLYTFile`**: Traverses layout pane hierarchies (`pan1`, `txt1`, `pic1`), expands text boxes, modifies font linkages, and adjusts texture coordinate matrices.
- **`BRLANFile`**: Keyframe animation editor (`RLAN` / `pai1`) adjusting animation sequences, frame timing, and pane visibility.

```python
from miorom.platforms.wii.brlyt import BRLYTFile
from miorom.platforms.wii.brlan import BRLANFile

lyt = BRLYTFile.from_bytes(open("message_box.brlyt", "rb").read())
# Adjust dialogue text box boundary
for pane in lyt.panes:
    if pane.name == "Txt_Dialogue":
        pane.width += 40.0

open("message_box_mod.brlyt", "wb").write(lyt.to_bytes())
```

### Sound Archive & Audio Streams (`BRSARArchive`, `BRSTMStream`)
Comprehensive audio reverse engineering and localization suite:
- **`BRSARArchive`**: Full reader and extractor for Nintendo Wii `.brsar` sound archives (`RSAR` / `SYMB`, `INFO`, `FILE`). Extracts sound collections, sound banks, and raw wave data.
- **`BRSTMStream`**: Multi-channel DSP-ADPCM streaming audio format with loop points (`HEAD`, `ADPC`, `DATA` chunks). Exports directly to multi-channel or stereo 16-bit WAV.

```python
from miorom.platforms.wii.brsar import BRSARArchive
from miorom.platforms.wii.brstm import BRSTMStream

# Extract all sound effects and sequences from sound archive
brsar = BRSARArchive.from_file("sound.brsar")
brsar.extract_all("extracted_audio/")

# Convert streaming BGM directly to WAV
brstm = BRSTMStream.from_file("bgm.brstm")
print(f"Channels: {brstm.channels}, Sample Rate: {brstm.sample_rate} Hz, Looped: {brstm.is_looped}")
open("bgm.wav", "wb").write(brstm.to_wav())
```

### Cinematic Movie Demuxer (`THPVideo`)
Demuxes Nintendo GameCube and Wii `.thp` video streams:
- Extracts Motion JPEG (MJPEG) intra-coded video frames.
- Demuxes synchronized multi-channel DSP-ADPCM audio streams to standard WAV.

```python
from miorom.platforms.wii.thp import THPVideo

thp = THPVideo.from_file("intro.thp")
print(f"Resolution: {thp.width}x{thp.height}, FPS: {thp.fps}, Frames: {thp.frame_count}")
video_frames = thp.extract_frames()
audio_wav = thp.extract_audio()
```

### Riivolution XML Patch Engine (`RiivolutionXML`)
Builds and audits SD/USB runtime patch packages for Nintendo Wii disc games without permanent ISO modification:
- Parses and generates `<wiidisc>`, `<section>`, `<option>`, `<choice>`, `<patch>`, `<folder>`, and `<file>` rules.

```python
from miorom.platforms.wii.riivolution import RiivolutionXML

riivo = RiivolutionXML(title="My Custom Translation")
riivo.add_disc_id("RMCE01")
riivo.add_replacement_folder(disc_path="/DATA/files/text", sd_path="/translation/text")
riivo.save("riivolution_mod.xml")
```

### WAD Package Container (`WADPackage`)
Parses and rebuilds Nintendo Wii WAD installation packages:
- Extracts and verifies certificate chains, tickets, TMD (Title Metadata), and encrypted/unencrypted content chunks.

```python
from miorom.platforms.wii.wad import WADPackage

wad = WADPackage.from_file("channel.wad")
print(f"Title ID: {wad.title_id}, Content Chunks: {len(wad.contents)}")
wad.extract_contents("wad_extracted/")
```

### Message Flowchart Binary (`MSBFFlowchart`)
Parses and relinks Nintendo Message Flowchart Binaries (`.msbf` / `FLW2`):
- Controls dialogue branch logic, choice menus, game state checks, and jump trees across Wii titles (e.g. *The Legend of Zelda: Skyward Sword*).

```python
from miorom.text.msbf import MSBFFlowchart

flow = MSBFFlowchart.from_file("event_dialogue.msbf")
print("Total flow nodes:", len(flow.nodes))
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

### Optical Disc & WBFS Sparse Container (`WiiDisc`, `WBFSDisc`, `WiiRomHandler`)
Production-grade Nintendo Wii optical disc (.iso / .wii) and WBFS container reverse engineering suite:
- **Streaming Decryption**: Lazy cluster decryption stream consuming <50 MB RAM for 8.5 GB retail DVD-9 images.
- **Wii Common Key & AES-128-CBC**: Automatically decrypts partition Title Keys using built-in retail (`ebe42a22...`) or Korean keys.
- **Hash Tree Hierarchy**: Traverses and verifies full 32 KB cluster hierarchy: H0 (31 sub-hashes) -> H1 -> H2 -> H3 hash trees.
- **Virtual Filesystem (FST)**: Traverses directory trees, reads files on-demand, and injects modified assets with automatic FST re-indexing.
- **Trucha Bug Fake-Signing**: Injects modified partition tickets and TMDs with valid zeroed RSA-2048 fake-signatures for homebrew compatibility.
- **WBFS Container**: Reads and serializes sparse block WBFS containers (`.wbfs`) with table-of-contents allocation maps.

```python
from miorom.platforms.wii import WiiDisc, WBFSDisc

# Load raw ISO or WBFS disc image
disc = WiiDisc.from_file("super_mario_galaxy.iso")
print(f"Game ID: {disc.header.game_id}, Disc Title: {disc.header.game_title}")

# Access data partition filesystem
partition = disc.get_data_partition()
print("Files in disc:", partition.list_files()[:5])

# Replace localized script file in FST
translated_script = open("event_text_en.bin", "rb").read()
partition.replace_file("DATA/files/event/message.bin", translated_script)

# Rebuild disc with Trucha bug fake-signing
disc.save("smg_translated.iso", fake_sign=True)
```

### Binary Texture Image (`BTIImage`)
Parser, builder, and texture converter for Nintendo standalone `.bti` images (common in *The Wind Waker*, *Super Mario Sunshine*, *Twilight Princess*):
- Supports official GX formats: CMPR (DXT1), RGB565, RGB5A3, RGBA8, I4, I8, IA4, IA8, and palette formats (C4, C8, C14X2).
- Preserves mipmap pyramids, LOD bias parameters, and texture clamping settings.
- Direct conversion to/from 32-bit RGBA pixel buffers and PIL Images.

```python
from miorom.platforms.wii import BTIImage

bti = BTIImage.from_file("title_logo.bti")
print(f"Dimensions: {bti.width}x{bti.height}, Format: {bti.format_name}, Mipmaps: {bti.image_count}")

# Export to PNG and replace
rgba_bytes = bti.decode_rgba()
new_bti = BTIImage.from_rgba(new_rgba_bytes, width=bti.width, height=bti.height, format_id=bti.format_id)
new_bti.save("title_logo_mod.bti")
```

### Resource Archive (`RARCArchive`)
Parser, extractor, and synthesizer for Nintendo RARC resource archives (`.arc`, `.rarc`):
- Full directory node hierarchy traversal with 16-bit filename hashing (`rarc_hash`).
- Maintains 32-byte alignment across MRAM, ARAM, and DVD resource sections.

```python
from miorom.platforms.wii import RARCArchive

# Extract all resources
RARCArchive.extract_all("Stage.arc", "Stage_extracted/")

# Repack modified resources into valid RARC container
RARCArchive.pack("Stage_extracted/", "Stage_mod.arc")
```

### Binary Revolution Resource & Texture Package (`BRRESFile`, `TEX0Image`)
Full parser, inspector, and texture injector for Nintendo Wii `.brres` model and texture resource containers:
- Reads and reconstructs Patricia trie directory index groups (`BresIndexGroup`).
- Direct access to `TEX0` texture banks (`TEX0Image`) and `PLT0` color palettes (`PLT0Palette`).
- Replaces textures in-place without rebuilding complex 3D bone hierarchies.

```python
from miorom.platforms.wii import BRRESFile

brres = BRRESFile.from_file("character_model.brres")
print("Textures in container:", list(brres.textures.keys()))

# Replace texture image
brres.replace_texture("chr_face", open("new_face.png", "rb").read())
brres.save("character_model_translated.brres")
```

### Relocatable Module Engine (`RelFile`, `DolBinary`)
PowerPC relocatable module (`.rel`) parser, linker, and runtime patcher for GameCube and Wii:
- Resolves ELF-like sections (`.text`, `.rodata`, `.data`, `.bss`) and PowerPC relocation chains (`R_PPC_ADDR32`, `R_PPC_ADDR16_LO`, `R_PPC_ADDR16_HA`, `R_PPC_REL24`).
- Links relocatable modules against static `DolBinary` main executables.

```python
from miorom.link.dol import RelFile, DolBinary

rel = RelFile.from_file("d_a_player.rel")
dol = DolBinary.from_file("main.dol")

# Link and resolve cross-module relocations
rel.link(dol)
print(f"Module ID: {rel.header.module_id}, Sections: {len(rel.sections)}")
```

### GameCube Disc & Executable Suite (`GameCubeDisc`, `DolFile`)
Comprehensive toolkit for GameCube optical disc images (`.iso`, `.gcm`) and executables (`main.dol`):
- **`GameCubeDisc`**: Reads and writes GameCube disc headers, FST hierarchies, boot banners, and apploaders.
- **`DolFile`**: Manages up to 7 text sections and 11 data sections. Translates between virtual RAM addresses and file offsets, provides memory read/write operations, and allocates new text sections for ASM code caves.

```python
from miorom.platforms.gc.disc import GameCubeDisc
from miorom.platforms.gc.dol import DolFile

# Load DOL executable
dol = DolFile.from_file("main.dol")
print(f"Text sections: {len(dol.text_sections)}, Entrypoint: 0x{dol.entry_point:08X}")

# Allocate a new text section for translation code cave
cave_offset, cave_ram = dol.allocate_code_cave(size=1024, address=0x80400000)
dol.write_memory(cave_ram, custom_ppc_machine_code)
dol.save("main_patched.dol")
```

### Message Studio Binary Text (`MSBTFile`)
Parser and builder for official Nintendo Message Studio Binary Text (`.msbt`):
- Manages `LBL1` (label hash table), `TXT2` (dialogue string pool), `ATR1` (attributes), and `TSY1` (style).
- Preserves embedded game control tags, ruby characters, and formatting commands across UTF-8 and UTF-16 encodings.

```python
from miorom.text.msbt import MSBTFile

msbt = MSBTFile.from_file("message.msbt")
for entry in msbt.entries:
    print(f"Label: {entry.label} -> {entry.text}")

# Update dialogue line
msbt.set_text("MSG_WELCOME", "Welcome, traveler! Prepare your journey.")
msbt.save("message_translated.msbt")
```

### Binary Message Pool (`BMGFile`)
Parser and serializer for Nintendo Binary Message files (`.bmg`):
- Manages `INF1` (message definition table) and `DAT1` (character string data) pools used across GameCube and Wii titles (e.g. *Mario Kart Wii*).
- Supports CP1252, Shift-JIS, and UTF-16-BE string pools with escape tag extraction.

```python
from miorom.text.bmg import BMGFile

bmg = BMGFile.from_file("Menu.bmg")
print(f"Total Messages: {len(bmg.messages)}")
bmg.set_message(index=0, text="START GAME")
bmg.save("Menu_mod.bmg")
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

### Unified Disc & ROM Engine (`PSXRom`, `PSXFormat`, `PSXRomHandler`)
Provides comprehensive inspection, virtual filesystem editing, executable management, and bit-exact dual sector serialization for PlayStation 1 disc images:
- **Dual Sector Formats**: Supports 2048-byte Mode 1 ISO disc images (`PSXFormat.ISO`) and 2352-byte Mode 2 Form 1 raw CD-ROM sector BIN images (`PSXFormat.BIN`).
- **Hardware EDC Recalculation**: Recomputes standard 32-bit EDC checksums across 2056 bytes per sector for Mode 2 Form 1 disc images.
- **`SYSTEM.CNF` Configuration**: Parses and edits boot paths, task control blocks (`TCB`), event limits (`EVENT`), and stack pointers (`STACK`).
- **Territory Resolution**: Identifies regional releases (`USA`, `EUR`, `JPN`, `ASIA`) from game product codes (`SLUS`, `SCUS`, `SLES`, `SCES`, `SLPS`, `SLPM`, `SCPS`, `SLAJ`).
- **Virtual Filesystem Operations**: Seamlessly lists, extracts, and replaces files with automated ISO 9660 sector reallocation and extent management when translation assets expand.
- **Executable Management**: Direct interface with `PSXExe` via `get_main_exe()` and `replace_main_exe()`.
- **CUE Sheet Generation**: Generates emulator-compliant CUE sheets (`generate_cue()`).
- **Deep Media Discovery**: Traverses the disc hierarchy to discover TIM textures (`find_textures()`), VAG audio streams (`find_audio()`), and STR movies (`find_videos()`).

```python
from miorom.platforms.psx import PSXRom, PSXFormat, resolve_psx_region

# Load PS1 BIN (2352 b/s Mode 2 Form 1) or ISO (2048 b/s Mode 1)
psx = PSXRom.from_file("game.bin")
print(f"Format: {psx.format.name}, Sector Size: {psx.sector_size} bytes")
print(f"Boot Executable: {psx.boot_path}, Game ID: {psx.game_id}")
print(f"Region: {psx.region}")

# Virtual Filesystem: Extract and replace translated script
script_bytes = psx.get_file("SCRIPT/STORY.BIN")
# ... modify script ...
psx.replace_file("SCRIPT/STORY.BIN", modified_script_bytes)

# Edit boot executable directly
main_exe = psx.get_main_exe()
if main_exe:
    # patch MIPS opcodes or strings...
    psx.replace_main_exe(main_exe)

# Save modified disc with bit-exact 32-bit EDC recalculation
psx.save("game_translated.bin")

# Generate companion CUE sheet
with open("game_translated.cue", "w") as f:
    f.write(psx.generate_cue("game_translated.bin"))
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

### Memory Card & Save Management (`PSXMemoryCard`, `PSXSaveFile`)
Complete Sony PlayStation 1 Memory Card manager and save block engine:
- Supports standard 128 KB (`.mcr`, `.mcd`, `.sav`) memory card images and individual save block (`.mcs`) files.
- Traverses 16 memory blocks (Block 0 directory frame with XOR checksums and Blocks 1..15 save data).
- Decodes 16x16 4bpp animated save icons (1 to 3 frames) with 16-color BGR555 palettes to PIL Images / PNG.
- Parses and updates localized Shift-JIS save titles, product codes, and frame checksums.

```python
from miorom.platforms.psx.memory_card import PSXMemoryCard

card = PSXMemoryCard.from_file("epsxe000.mcr")
print(f"Free Blocks: {card.free_blocks}, Saves: {len(card.saves)}")

for save in card.saves:
    print(f"Title: {save.title}, Product Code: {save.product_code}, Blocks: {save.block_count}")
    # Export animated save icon frames to PNG
    for idx, icon in enumerate(save.icons):
        icon.save(f"{save.product_code}_icon_{idx}.png")

# Modify save title
card.saves[0].title = "Final Fantasy VII (Indonesian)"
card.save("epsxe_translated.mcr")
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

### Unified Cartridge Engine (`GBARom`, `GBARomHandler`)
MioROM provides a production-grade Game Boy Advance ROM hacking and translation engine:
- **Header Inspection & Validation**: Parses 192-byte header (`GBAHeaderStruct`), entry point branch opcode, title, game code, maker code, version, and Nintendo logo bitmap.
- **Hardware Complement Checksum**: Automatically recalculates and repairs the header complement check byte at offset `0xBD` using `chk = (SUM_{0xA0..0xBC} - 0x19) & 0xFF` (`calculate_header_checksum()`, `is_header_checksum_valid()`, `fix_header_checksum()`).
- **Nintendo Logo Verification & Repair**: Checks official 156-byte logo integrity (`is_logo_valid()`) and restores official logo bitmap in-place (`fix_logo()`).
- **Real-Time Clock (RTC) Detection**: Detects official `b"SIIRTC_V"` (e.g. `SIIRTC_V001`) library signatures (`has_rtc`) and combines with backup chip signatures in `detect_save_type()`.
- **Backup Hardware Detection & SRAM Patching**: Detects EEPROM (4K/64K), SRAM (256K), FLASH512, and FLASH1M signatures. Converts Flash/EEPROM save calls to standard 32KB SRAM (`patch_save_to_sram()`) for flashcarts and emulators.
- **Capacity Management**: Expands ROM images up to 64 MB (`expand(1, 2, 4, 8, 16, 32, 64)`) with hardware-accurate `0xFF` Flash memory padding; trims trailing padding (`trim()`).
- **32-Bit Memory Pointer Translation & Relinking**: Maps between file byte offsets and GBA Game Pak bus addresses (`0x08000000..0x0DFFFFFF`, Waitstates 0, 1, 2) via `ptr_to_offset()` and `offset_to_ptr()`. Automatically discovers references (`find_pointers()`) and updates pointers when strings/tables are relocated to expanded ROM areas (`relink_pointers()`).
- **BIOS SWI Call Scanner**: Directly scans ROM executable code for GBA BIOS software interrupts (`scan_swi_calls()`), resolving routines such as `LZ77UnCompWram` (`0x11`), `CpuSet` (`0x0B`), and `RegisterRamReset` (`0x01`).
- **Deep Media Discovery**: Forensically scans for embedded Nintendo LZ77 Type 0x10 streams (`find_lz10_streams()`) and Music Player 2000 / Sappy song tables (`find_sappy_songs()`).
- **RomManager Integration**: Registered as `"gba"` handler with high precedence ahead of generic cartridge fallbacks, providing automated `unpack()` and `repack()` with JSON manifest metadata.

```python
from miorom.platforms.gba import GBARom, resolve_gba_region

rom = GBARom.from_file("zelda_minish_cap.gba")
print(f"Title: {rom.title}, Game Code: {rom.game_code}, Region: {rom.region}")
print(f"Save Type: {rom.detect_save_type()}, Has RTC: {rom.has_rtc}")
print(f"Entry Point: 0x{rom.entry_point:08X}")

# Expand ROM to 32 MB for translation script insertion
rom.expand(target_size_mb=32)

# Memory pointer translation and surgical relinking
old_dialogue_offset = 0x00200000
new_dialogue_offset = 0x01500000
pointers_found = rom.find_pointers(old_dialogue_offset)
print(f"Found {len(pointers_found)} pointer references to dialogue table.")

# Relink all pointers to the expanded free space
relinked_count = rom.relink_pointers(old_dialogue_offset, new_dialogue_offset)
print(f"Relinked {relinked_count} pointers.")

# Scan embedded BIOS LZ77 compressed graphics and Sappy song tables
lz_streams = rom.find_lz10_streams(min_size=1024)
sappy_tables = rom.find_sappy_songs(min_consecutive=4)
print(f"Found {len(lz_streams)} LZ10 streams and {len(sappy_tables)} Sappy song tables.")

# Patch save to SRAM for flashcart compatibility
if "FLASH" in rom.detect_save_type():
    rom.patch_save_to_sram()

# Fix complement checksum and save
rom.save("zelda_translated.gba", fix_checksum=True)
```

### Multiboot & BIOS SWI Engine (`GBAMultiboot`, `GBASwiResolver`)
- **`GBAMultiboot`**: Synthesizes and validates 256KB EWRAM Multiboot `.mb` payloads transmitted via Joybus cable.
- **`GBASwiResolver`**: Resolves all official GBA BIOS software interrupt calls with disassembly instruction annotations:

```python
from miorom.platforms.gba import GBASwiResolver, GBAMultiboot

# Annotate Thumb SWI instruction
annotation = GBASwiResolver.annotate_thumb_instruction(0xDF11)
print(annotation)  # "SWI 0x11 (LZ77UnCompWram)"

# Create a valid multiboot payload
mb_payload = GBAMultiboot.create_payload(
    code_bytes=boot_code,
    title="POKEMON_MB",
    game_code="PKMB",
    maker_code="01",
)
```

### Sappy / Music Player 2000 Sound Engine (`SappyScanner`, `SappyCodec`)
Pure-Python scanner and ripper for GBA DirectSound PCM samples:
- Parses Sappy voice tables and song tables.
- Extracts signed 8-bit PCM audio samples and exports directly to 16-bit WAV files.

```python
from miorom.audio.sappy import SappyScanner, SappyCodec

rom_bytes = open("game.gba", "rb").read()
song_tables = SappyScanner.scan_song_tables(rom_bytes)
if song_tables:
    songs = SappyScanner.parse_song_table(rom_bytes, song_tables[0])
    print(f"Found {len(songs)} song entries in table at 0x{song_tables[0]:X}.")
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

### Unified Disc & Package ROM Engine (`PSPRom`, `PSPFormat`, `PSPRomHandler`)
High-level orchestrator for Sony PlayStation Portable games across all package and disc formats:
- Supports uncompressed UMD ISO (`.iso`), compressed CSO (`.cso`), and EBOOT packages (`.pbp`).
- Seamless format cross-conversion (`to_bytes(PSPFormat.CSO)` or `save(path, PSPFormat.PBP)`).
- Full virtual filesystem access (`list_files`, `get_file`, `replace_file`) with automated ISO 9660 sector reallocation.
- Live VSH / XMB multimedia asset editing (`set_title()`, `set_icon()`, `set_background()`, `set_boot_audio()`).
- Direct executable manager (`get_boot_bin()`, `replace_boot_bin()`, `get_eboot_bin()`, `replace_eboot_bin()`).
- Regional territory code resolution (`resolve_psp_region`).

```python
from miorom.platforms.psp import PSPRom, PSPFormat

# Open PSP ISO, CSO, or PBP seamlessly
rom = PSPRom.from_file("game.iso")
print(f"Format: {rom.format.name}, Title: {rom.title}, Game ID: {rom.game_id}, Region: {rom.region}")

# Update XMB background graphic and menu title
rom.set_background(open("new_pic1.png", "rb").read())
rom.set_title("My Custom Translation")

# Replace translated dialogue file in ISO filesystem
rom.replace_file("PSP_GAME/USRDIR/text/dialogue.bin", open("dialogue_mod.bin", "rb").read())

# Export directly to compressed CSO format for memory cards
rom.save("game_compressed.cso", fmt=PSPFormat.CSO)
```

### Relocatable MIPS Executable & NID Resolver (`PRXModule`, `PSPNIDResolver`)
Parser, builder, and dynamic stub hooker for Sony PlayStation Portable relocatable executables (`.prx` / `BOOT.BIN` / `EBOOT.BIN`):
- Parses 32-bit Little-Endian MIPS ELF headers and `sceModuleInfo` descriptors.
- Identifies encrypted `~PSP` payloads and directs users to decrypted binaries.
- Algorithmic SHA-1 32-bit NID calculation (`calculate_nid()`) with offline lookup database (~150+ official Sony SDK function names).
- Function call stub hooking (`redirect_stub()`) and dynamic NID swapping (`replace_import_nid()`).

```python
from miorom.platforms.psp.prx import PRXModule, PSPNIDResolver

prx = PRXModule.from_file("BOOT.BIN")
print(f"Module: {prx.info.name}, User Mode: {prx.info.is_user_mode}")

# Resolve imported SDK APIs
for lib in prx.imports:
    print(f"Library: {lib.name}")
    for nid in lib.function_nids:
        func_name = PSPNIDResolver.resolve_nid(nid)
        print(f"  NID 0x{nid:08X} -> {func_name or 'Unknown'}")

# Hook font rendering or dialogue routine
prx.redirect_stub(stub_address=0x08900100, target_address=0x08980000)
prx.save("BOOT_HOOKED.BIN")
```

### ATRAC3 & ATRAC3plus Audio Engine (`AT3Audio`, `AT3Codec`)
Parser, serializer, and seamless BGM loop point editor for Sony PSP RIFF WAVE audio streams:
- Distinguishes standard ATRAC3 (`0x0270`) and ATRAC3plus (`0xFFFE` extensible GUID).
- Edits `'smpl'` chunk loop points (`set_loop(start_sample, end_sample)`) to prevent BGM stuttering or muting.
- Replaces audio stream payloads (`replace_data()`) with automated recalculation of `'data'`, `'fact'`, and `'RIFF'` chunk boundaries.

```python
from miorom.platforms.psp.at3 import AT3Audio

at3 = AT3Audio.from_file("SND0.AT3")
print(f"Codec: {at3.codec_name}, Sample Rate: {at3.sample_rate} Hz, Channels: {at3.channels}")

# Set seamless loop points for custom background music
at3.set_loop(start_sample=44100, end_sample=2205000)
at3.save("SND0_LOOPED.AT3")
```

### GIM Textures & Hardware Swizzling (`GIMImage`, `psp_swizzle`, `psp_unswizzle`)
Parser, serializer, and hardware swizzler for Sony PSP GIM (`.gim`) texture graphics:
- Supports PSP GE pixel formats: RGBA5650, RGBA5551, RGBA4444, RGBA8888, Index4, and Index8.
- Hardware VRAM swizzling/unswizzling (`psp_swizzle()`, `psp_unswizzle()`) organizing linear raster scanlines into 16-byte memory blocks for high-speed GPU texture sampling.
- Bidirectional conversion to/from PNG images.

```python
from miorom.platforms.psp.pbp import GIMImage, psp_swizzle, psp_unswizzle

gim = GIMImage.from_file("icon.gim")
print(f"Dimensions: {gim.width}x{gim.height}, Format: {gim.format.name}")

# Export to PNG
png_image = gim.to_png()
png_image.save("icon.png")

# Swizzle linear image buffer for PSP GPU
swizzled_bytes = psp_swizzle(raw_pixels, width=256, height=128, bpp=32)
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


