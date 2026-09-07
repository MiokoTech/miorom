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

Creates distribution patches comparing original and modified ROM files. Supports IPS (up to 16MB), BPS (with CRC32 integrity checks), and Xdelta (VCDIFF delta compression for large ISOs).

```bash
miorom patch-create <original> <modified> -o <output_patch> [-f FORMAT]
```

#### Arguments & Options
- `original`: Path to unmodified ROM.
- `modified`: Path to modified ROM.
- `-o, --output`: Target patch filename.
- `-f, --format`: Patch format (`ips`, `bps`, `xdelta`). Default: `bps`.

#### Examples
```bash
# Create an Xdelta patch for a Wii/GameCube disc image
miorom patch-create "clean.iso" "translated.iso" -o "patch.xdelta" -f xdelta

# Create a BPS patch for a GBA ROM
miorom patch-create "game.gba" "game_id.gba" -o "patch.bps" -f bps
```

---

### 6. `patch-apply` - Binary Patch Applicator

Applies an IPS, BPS, or Xdelta patch to an original ROM file.

```bash
miorom patch-apply <original> <patch> -o <output_file> [-f FORMAT]
```

#### Arguments & Options
- `original`: Path to unmodified ROM.
- `patch`: Path to distribution patch file.
- `-o, --output`: Path for output patched file.
- `-f, --format`: (Optional) Patch format (`ips`, `bps`, `xdelta`). Auto-detected if omitted.

#### Example
```bash
miorom patch-apply "clean.iso" "patch.xdelta" -o "game_patched.iso"
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
- `-f, --format`: Compression format (`lz10`, `lz11`, `rle`, `yaz0`, `huffman4`, `huffman8`).

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
