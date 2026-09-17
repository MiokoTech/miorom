# MioROM Command-Line Interface (CLI) Reference

MioROM includes a command-line interface (`miorom`) designed to automate routine reverse engineering, ROM extraction, binary inspection, patch generation, and translation batching workflows directly from the terminal.

---

## Global Syntax

```bash
miorom <subcommand> [options] [arguments]
```

To display global help and version information:

```bash
miorom --help
miorom --version
```

---

## Command Reference

### 1. `unpack` - Universal ROM & Container Extraction

Unpacks bootable ROMs, disk images, and containers into `sys/` (system headers and executables) and `root/` (filesystem data) with a `miorom.meta.json` manifest.

```bash
miorom unpack <rom_file> <output_dir> [-f FORMAT]
```

#### Arguments & Options
- `rom_file`: Path to the input ROM or container.
- `output_dir`: Target directory for extracted assets.
- `-f, --format`: (Optional) Force container format (`nds`, `gc`, `u8`, `narc`, `iso`, `cartridge`). If omitted, format is auto-detected.

#### Examples
```bash
# Unpack a Nintendo DS ROM
miorom unpack "game.nds" "extracted_nds/"

# Unpack a GameCube / Wii ISO image
miorom unpack "game.iso" "extracted_iso/"

# Unpack a Nintendo U8 archive
miorom unpack "banner.arc" "extracted_arc/" -f u8
```

---

### 2. `repack` - Universal ROM & Container Reconstruction

Repacks directory trees into bit-aligned, hardware-compliant ROM images with automatic checksum recalculation (NDS CRC16, GBA complement, N64 CIC, etc.).

```bash
miorom repack <input_dir> <output_file> [-f FORMAT]
```

#### Arguments & Options
- `input_dir`: Directory containing `sys/`, `root/`, and `miorom.meta.json`.
- `output_file`: Destination path for the rebuilt ROM file.
- `-f, --format`: (Optional) Force target container format.

#### Examples
```bash
# Repack an unpacked Nintendo DS directory
miorom repack "extracted_nds/" "game_patched.nds"

# Repack a GameCube ISO directory
miorom repack "extracted_iso/" "game_repacked.iso"
```

---

### 3. `inspect` - Smart Binary & Container Inspector

Analyzes any unknown file or binary segment. Generates a forensic report including Shannon block entropy profiling, container fingerprints, multi-encoding probing (Shift-JIS, UTF-8, UTF-16, ASCII), and pointer table candidates.

```bash
miorom inspect <input_file>
```

#### Arguments & Options
- `input_file`: Path to the binary file to analyze.

#### Example
```bash
miorom inspect unknown_data.bin
```

---

### 4. `scan` - Text & Pointer Table Discovery

Scans binary files for text strings, detects contiguous text blocks, and searches for pointer tables referencing discovered strings. Can export directly to a translation CSV.

```bash
miorom scan <input_file> [-e ENCODING] [--min-len N] [--pointers] [--footer-scan BYTES] [--orphans] [--deep] [-o OUTPUT_CSV]
```

#### Arguments & Options
- `input_file`: Binary file to scan.
- `-e, --encoding`: Text encoding (`shift_jis`, `utf-8`, `utf-16-be`, `utf-16-le`, `ascii`). Default: `utf-8`.
- `--min-len`: Minimum string length in characters. Default: `4`.
- `--pointers`: Search for candidate pointer tables.
- `--footer-scan`: Bytes to scan from the end of the file for secondary/footer pointer tables.
- `--orphans`: Identify strings not referenced by any detected pointer table.
- `--deep`: Run recursive format signature detection.
- `-o, --output`: Export discovered dialogue strings to a CSV file.

#### Example
```bash
# Scan a binary script for Shift-JIS text and export with pointers to CSV
miorom scan script.bin -e shift_jis --pointers --orphans -o script_dialog.csv
```

---

### 5. `patch-create` - Binary Patch Generator

Creates distribution patches comparing original and modified ROM files. Supports IPS (up to 16MB), BPS (with CRC32 integrity checks), UPS (with bi-directional CRC32 verification), and Xdelta (VCDIFF delta compression for large ISOs).

```bash
miorom patch-create <original> <modified> -o <output_patch> [-f FORMAT]
```

#### Arguments & Options
- `original`: Path to unmodified ROM.
- `modified`: Path to modified ROM.
- `-o, --output`: Target patch filename.
- `-f, --format`: Patch format (`ips`, `bps`, `ups`, `xdelta`). Default: `bps`.

#### Examples
```bash
# Create an Xdelta patch for a Wii/GameCube disc image
miorom patch-create "clean.iso" "translated.iso" -o "patch.xdelta" -f xdelta

# Create a BPS patch for a GBA ROM
miorom patch-create "game.gba" "game_id.gba" -o "patch.bps" -f bps

# Create a UPS patch for a GBA ROM
miorom patch-create "game.gba" "game_id.gba" -o "patch.ups" -f ups
```

---

### 6. `patch-apply` - Binary Patch Applicator

Applies an IPS, BPS, UPS, or Xdelta patch to an original ROM file.

```bash
miorom patch-apply <original> <patch> -o <output_file> [-f FORMAT]
```

#### Arguments & Options
- `original`: Path to unmodified ROM.
- `patch`: Path to distribution patch file.
- `-o, --output`: Path for output patched file.
- `-f, --format`: (Optional) Patch format (`ips`, `bps`, `ups`, `xdelta`). Auto-detected if omitted.

#### Example
```bash
miorom patch-apply "clean.iso" "patch.xdelta" -o "game_patched.iso"
```

---

### 6b. `patch export-riivolution` & `patch apply-riivolution` - Nintendo Wii Mod Loader

Export delta assets and generate compliant Riivolution XML mod distributions, or apply Riivolution XML mods directly into Wii disc images (`.iso`, `.wbfs`, `.rvz`).

```bash
# Export delta assets to Riivolution SD card layout
miorom patch export-riivolution --orig <unpacked_orig_dir> --mod <modified_dir> -n <mod_name> --id <game_id> -o <sdcard_dir>

# Apply Riivolution mod into a playable disc image
miorom patch apply-riivolution --disc <clean_disc> --xml <mod.xml> --root <mod_assets_dir> -o <patched_disc>
```

---

### 7. `compress` - Console BIOS Compressor

Compresses data using console-standard compression algorithms.

```bash
miorom compress <input_file> -o <output_file> -f FORMAT
```

#### Arguments & Options
- `input_file`: Uncompressed raw file.
- `-o, --output`: Path for compressed output file.
- `-f, --format`: Compression format (`lz10`, `lz11`, `rle`, `yaz0`, `yay0`, `aplib`, `huffman4`, `huffman8`).

#### Example
```bash
# Compress a font binary using Nintendo DS/Wii LZ11
miorom compress font.bin -o font.bin.lz -f lz11
```

---

### 8. `decompress` - Console BIOS Decompressor

Decompresses binary assets, automatically identifying the compression format from header magic bytes.

```bash
miorom decompress <input_file> -o <output_file>
```

#### Example
```bash
miorom decompress font.bin.lz -o font_decompressed.bin
```

---

### 9. `split` - CSV Translation Batch Splitter

Splits a large dialogue CSV file into manageable batch chunks for distributed translation teams.

```bash
miorom split <input_csv> -o <output_dir> [-s SIZE] [-p PREFIX]
```

#### Arguments & Options
- `input_csv`: Master CSV file containing dialogue rows.
- `-o, --output-dir`: Target directory for generated batch files.
- `-s, --size`: Number of rows per batch file. Default: `500`.
- `-p, --prefix`: Filename prefix for generated batches. Default: `batch_`.

#### Example
```bash
miorom split dialogue_master.csv -o translation_batches/ -s 250
```

---

### 10. `merge` - CSV Translation Batch Merger

Merges translated batch CSV files back into a master translation CSV file, verifying row indices.

```bash
miorom merge <batch_dir> -o <output_csv> [-m MASTER_CSV]
```

#### Arguments & Options
- `batch_dir`: Directory containing translated batch files.
- `-o, --output-csv`: Merged master CSV destination.
- `-m, --master`: (Optional) Original master CSV file used for baseline comparison.

#### Example
```bash
miorom merge translation_batches/ -o dialogue_translated.csv -m dialogue_master.csv
```

---

### 11. `validate` - Textbox Overflow Validator

Audits a translation CSV against specified character-per-line and lines-per-box constraints to prevent in-game text clipping.

```bash
miorom validate <csv_file> [--max-chars N] [--max-lines N]
```

#### Arguments & Options
- `csv_file`: Translation CSV to validate.
- `--max-chars`: Maximum allowed characters per line. Default: `36`.
- `--max-lines`: Maximum allowed lines per dialogue box. Default: `3`.

#### Example
```bash
miorom validate dialogue_translated.csv --max-chars 38 --max-lines 3
```

---

### 12. `toc` - Paired Archive Inspector & Injector

Manages paired index/data archives (`.bin` TOC + `.dat` payload), allowing listing, extraction, and in-place injection without loading entire gigabyte archives into RAM.

```bash
miorom toc list <bin_file> <dat_file> [--limit N]
miorom toc extract <bin_file> <dat_file> <index> -o <output_file>
miorom toc inject <bin_file> <dat_file> <index> <input_file> [--out-bin PATH] [--out-dat PATH]
```

#### Examples
```bash
# List entries in a TOC pair
miorom toc list system.bin system.dat --limit 20

# Extract subfile at index 42
miorom toc extract system.bin system.dat 42 -o subfile_42.bin

# Inject modified subfile back into the archive
miorom toc inject system.bin system.dat 42 subfile_42_mod.bin
```

---

### 13. `cheat` - Action Replay & Gecko Cheat Generator

Generates RAM cheat codes by comparing original and modified binaries, producing Gecko, Action Replay, CWCheat, or GameShark codes.

```bash
miorom cheat <original> <modified> --base ADDRESS [--type TYPE] [--game-id ID] [--title TITLE] [-o OUTPUT]
```

#### Arguments & Options
- `original`: Unmodified binary.
- `modified`: Modified binary.
- `--base`: Base RAM address (e.g., `0x80000000`).
- `--type`: Code format (`gecko`, `ar`, `cwcheat`, `gameshark`). Default: `gecko`.
- `--game-id`: Target game ID (e.g., `RFFE01`).
- `--title`: Cheat code label.
- `-o, --output`: Optional output file path.

#### Example
```bash
miorom cheat original.bin modified.bin --base 0x80200000 --type gecko --game-id RF3E01 -o cheats.txt
```

---

### 14. `port-csv` - Cross-Region Translation Porter

Transfers existing translations from one regional version (e.g. Japanese release) to another (e.g. USA/European release) using text matching or binary address correlation.

```bash
miorom port-csv --source-csv JP.csv --target-csv US.csv -o US_translated.csv [--strategy STRATEGY]
```

#### Arguments & Options
- `--source-csv`: Source translation CSV.
- `--target-csv`: Target regional CSV to populate.
- `-o, --output`: Output path for ported CSV.
- `--strategy`: Matching strategy (`text`, `offset`, `hybrid`). Default: `text`.

---

### 15. `scan-text` - Multi-Byte Japanese Binary Text Scanner

Scans unmapped ROM blobs for continuous dialogue and script tables encoded in Shift-JIS, EUC-JP, UTF-16, or ASCII using strict lead-byte/trail-byte FSM validation.

```bash
miorom scan-text <input_file> [-e ENCODINGS] [-l MIN_LEN] [-c MIN_CONF] [--table] [-n LIMIT] [-o OUTPUT]
```

#### Arguments & Options
- `input_file`: Path to raw ROM or binary dump.
- `-e, --encodings`: Comma-separated encodings (e.g. `sjis,euc_jp,ascii`). Default: `sjis,euc_jp,ascii`.
- `-l, --min-len`: Minimum character run length. Default: `4`.
- `-c, --min-conf`: Confidence threshold (0.0 to 1.0). Default: `0.65`.
- `--table`: Detect and group continuous null-delimited string table clusters.
- `-n, --limit`: Maximum individual text spans to print. Default: `20`.
- `-o, --output`: Optional output JSON file path.

---

### 16. `disasm` - Multi-Architecture Machine Code Disassembler

Disassembles machine code across 8 retro architectures (MOS 6502, W65C816, Z80, SM83, M68K, ARM, Thumb, MIPS, PowerPC).

```bash
miorom disasm <input_file> [-a ARCH] [-o OFFSET] [-n COUNT] [-b BASE]
```

#### Arguments & Options
- `input_file`: Path to binary file containing code.
- `-a, --arch`: Architecture (`6502`, `65816`, `z80`, `sm83`, `m68k`, `arm`, `thumb`, `mips`, `ppc`). Default: `m68k`.
- `-o, --offset`: File start offset. Default: `0`.
- `-n, --count`: Number of instructions to decode. Default: `32`.
- `-b, --base`: Virtual memory PC base address. Default: same as offset.

---

### 17. `checksum` - Retro Header & Binary Checksum Tool

Calculates, verifies, and optionally fixes hardware checksums for SNES, Sega Genesis, Game Boy, and N64.

```bash
miorom checksum <input_file> [-s SYSTEM] [--fix]
```

#### Arguments & Options
- `input_file`: Path to ROM file.
- `-s, --system`: Checksum algorithm (`snes`, `genesis`, `gb`, `all`). Default: `all`.
- `--fix`: Recalculate and patch the checksum in-place if mismatched.

---

### 18. `reloc-branch` - PC-Relative Branch Rebasing Engine

Recalculates relative branch displacements when shifting code routines across memory addresses.

```bash
miorom reloc-branch <input_file> -a ARCH --orig-base ADDR --new-base ADDR [-o OUTPUT]
```

#### Arguments & Options
- `input_file`: Path to binary file containing machine code.
- `-a, --arch`: Architecture (`6502`, `65816`, `z80`, `sm83`, `m68k`, `arm`, `thumb`, `mips`).
- `--orig-base`: Original PC address of the routine.
- `--new-base`: New PC destination address.
- `-o, --output`: Output file path (default: overwrite input).

---

### 19. `tile-dedup` - 8x8 Tile Deduplicator & VRAM Optimizer

Deduplicates 8x8 tiles in a binary planar graphics buffer, matching identical tiles and symmetrical flipped copies (H-flip, V-flip).

```bash
miorom tile-dedup <input_file> [--bpp BPP] [-f FORMAT] [--no-h-flip] [--no-v-flip] [-o OUTPUT]
```

#### Arguments & Options
- `input_file`: Path to raw tile binary file.
- `--bpp`: Bits per pixel (`1`, `2`, `4`). Default: `4`.
- `-f, --format`: Optional format name (e.g. `2bpp`, `4bpp_planar`, `genesis_4bpp`).
- `--no-h-flip`: Disable horizontal flip matching.
- `--no-v-flip`: Disable vertical flip matching.
- `-o, --output`: Output path for deduplicated tile binary.

---

### 20. `inject-elf` - ELF C/ASM Payload Linker & Injector

Links and injects a compiled C/ASM ELF object file directly into an executable binary (e.g. GameCube/Wii `main.dol`, NDS `arm9.bin`, or flat ROM binary). Automatically resolves relocations, allocates or targets a code cave, and installs an entry hook trampoline.

```bash
miorom inject-elf <target_bin> <payload_elf> [options]
```

#### Arguments & Options
- `target_bin`: Target executable or ROM dump (e.g. `main.dol`, `arm9.bin`).
- `payload_elf`: Compiled ELF object file (`.o` or `.elf`).
- `-o, --output`: Output patched binary path (default: overwrite target).
- `--hook`: Hook RAM address to hijack (e.g. `0x80001234`).
- `--hook-offset`: Explicit hook file offset.
- `--cave`: Code cave destination RAM address (e.g. `0x80500000`).
- `--cave-offset`: Explicit code cave file offset.
- `-b, --base`: Base RAM load address for flat binaries (default: `0`).
- `-s, --symbols`: Path to external symbol map file (`.sym`, `.map`, `.json`, `.csv`).
- `-e, --entry`: Payload entry function name (default: auto-detected).
- `-a, --arch`: Target CPU architecture override (`ppc`, `arm`, `thumb`, `mips_le`, `mips_be`).
- `-m, --hook-mode`: Hook mechanism (`trampoline`, `call`, `replace`). Default: `trampoline`.

#### Example
```bash
miorom inject-elf main.dol custom_vwf.o --hook 0x80054320 --cave 0x805A0000 -m trampoline -o main_mod.dol
```

---

### 21. `port-patch` - Cross-Region Binary Patch Porter

Translates an IPS patch made against one regional game binary (e.g. Japanese release) into a corresponding patch for a target regional release (e.g. USA release) using symbolic BinDiff function matching.

```bash
miorom port-patch --from <source_bin> --to <target_bin> --patch <source.ips> -o <target.ips> [options]
```

#### Arguments & Options
- `--from`: Source-region binary against which the original patch was created.
- `--to`: Target-region binary to port the patch to.
- `--patch`: Input source-region IPS patch.
- `-o, --output`: Output translated IPS patch path.
- `--source-base`: Base address for source binary (default: `0`).
- `--target-base`: Base address for target binary (default: `0`).
- `-a, --arch`: Lifter architecture (`ppc`, `arm`, `thumb`, `mips_le`, `mips_be`). Default: `ppc`.
- `--threshold`: BinDiff isomorphism confidence threshold (0.0 to 1.0). Default: `0.75`.

---

### 22. `gfx` - Forensic Texture Inspector & Visual Diffing

Forensic analysis, visual regression comparison, ASCII terminal rendering, and translated text banner recomposition for game textures (TPL, BTI, PNG).

```bash
miorom gfx <subcommand> [options] [arguments]
```

#### Subcommands

##### `gfx inspect`
Performs structural integrity analysis on texture files, verifying dimensions, format bit depths, palette capacity, and tile alignment.

```bash
miorom gfx inspect <input_file> [--json]
```

##### `gfx ascii`
Renders a terminal-friendly ASCII grayscale representation of the texture image.

```bash
miorom gfx ascii <input_file> [-w WIDTH]
```

##### `gfx diff`
Mathematically computes visual differences between an original reference texture and a modified texture, reporting modified pixel count, percentage, bounding box, and max channel delta.

```bash
miorom gfx diff <original_file> <modified_file> [--json]
```

##### `gfx recompose`
Harvests glyph sprites from a reference graphic banner and recomposes a target localized phrase with customizable tracking, space width, border overlap, and alignment.

```bash
miorom gfx recompose <source_image> -t <target_phrase> -o <output.png> [options]
```

---

### 23. `vfs` - Nested Container Virtual File System

Traverses, extracts, and mutates files inside deeply nested container hierarchies (e.g. `outer.arc::inner.arc::path/to/texture.tpl`) with automatic outward recompression and sector alignment.

```bash
miorom vfs <subcommand> [options] [arguments]
```

#### Subcommands

##### `vfs list`
Lists all files and directories located inside a nested container URI.

```bash
miorom vfs list <uri>
```

##### `vfs read`
Extracts a specific nested file directly to disk.

```bash
miorom vfs read <uri> -o <output_file>
```

##### `vfs write`
Injects a modified local file into a nested container path and atomically rebuilds all parent archives outward.

```bash
miorom vfs write <uri> -i <input_file>
```

---

### 24. `audio` - Multi-Format Audio Codec, Converter & Container Ripper

Converts audio files between standard PCM WAV and console-native ADPCM codecs (Sony PS1 VAG, SNES SPC700 BRR, Nintendo GameCube/Wii DSP-ADPCM), inspects stream metadata, and extracts sound samples from console containers (`.spc`, `.sdat`).

```bash
miorom audio <subcommand> [options] [arguments]
```

#### Subcommands

##### `audio convert`
Converts audio files between WAV, VAG (PS1/PS2), BRR (SNES), and DSP-ADPCM (GameCube/Wii).

```bash
miorom audio convert <input_file> -o <output_file> [-r RATE] [-c CHANNELS] [-l LOOP] [--from-format FMT] [--to-format FMT]
```

###### Examples
```bash
# Convert a WAV sound effect to Sony PS1 VAG
miorom audio convert "sfx.wav" -o "sfx.vag" -r 22050 -c 1

# Convert a SNES BRR sample back to playable WAV
miorom audio convert "jump.brr" -o "jump.wav" -r 32000

# Convert stereo WAV to Nintendo DSP-ADPCM
miorom audio convert "bgm.wav" -o "bgm.dsp" -r 44100 -c 2
```

##### `audio extract`
Extracts all embedded waveform samples and sound banks from console audio containers directly into standard 16-bit PCM `.wav` files.

```bash
miorom audio extract <container_file> -o <output_dir> [-r RATE]
```

###### Examples
```bash
# Extract all instrument samples from a SNES .spc sound file
miorom audio extract "theme.spc" -o "extracted_spc_samples/"

# Extract audio streams from a Nintendo DS .sdat sound archive
miorom audio extract "sound_data.sdat" -o "extracted_sdat_wavs/"
```

##### `audio info`
Inspects audio file headers, duration, channel configuration, sampling rates, and loop points.

```bash
miorom audio info <input_file> [--json]
```

###### Examples
```bash
# Inspect a Nintendo Wii BRSTM or GameCube DSP audio file
miorom audio info "track01.brstm"

# Export metadata in JSON format
miorom audio info "voice.vag" --json
```

