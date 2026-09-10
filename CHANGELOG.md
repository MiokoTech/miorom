# Changelog

All notable changes to MioROM will be documented in this file.

## [0.13.1] — 2026-09-10

### Added
- **Flexible Buffer Support in `PatchWriter` (`miorom.patch.patch_writer`)**:
  - `PatchWriter.__init__` now accepts `Union[bytes, bytearray]`, automatically casting immutable `bytes` to a mutable `bytearray` when needed.
- **Documentation Design with MkDocs Material**:
  - Added documentations.


## [0.13.0] — 2026-09-10

### Added
- **DMA Filesystem Abstraction (`miorom.archive.dma`)**:
  - Declarative `DmaTableEntryStruct` via `BinaryStruct`.
  - `DmaTableArchive` and `DmaFileEntry` for parsing, querying, extracting, and decompressing N64 DMA filesystems (Zelda OoT, Pokemon Stadium, Animal Forest).
- **MIPS COP1 (Floating Point) & Architecture Expansion (`miorom.asm`, `miorom.script`)**:
  - Added full MIPS COP1 float instruction decoder to `UniversalDisassembler`: `lwc1`, `ldc1`, `swc1`, `sdc1`, `mfc1`, `mtc1`, `add.s`, `sub.s`, `mul.s`, `div.s`, `c.lt.s`, `bc1t`, `bc1f`.
  - Added SM83 (Game Boy) and Motorola 68000 (Sega Mega Drive) instruction decoding and SSA IR lifting.
  - Added fluent MIPS snippet assembly builder methods (`li`, `lw`, `sw`, `addu`, `subu`, `sll`, `srl`, `ori`, `andi`, `move`, `j`, `jal`) to `MipsSnippet`.
- **Fast3D Microcode Pipeline (`miorom.graphics.fast3d`)**:
  - `Fast3DParser`: Discovers texture descriptors (`F3DTextureDescriptor`), dimensions, and formats from N64 microcode streams (`G_SETTIMG`, `G_SETTILE`, `G_SETTILESIZE`, `G_LOADBLOCK`).
  - `Fast3DBuilder`: Fluent Python emitter for N64 display lists (`set_timg`, `set_tile`, `set_tile_size`, `load_block`, `end_dl`).
- **N64 Fast3D Textures (`miorom.graphics.n64_texture`)**:
  - Pixel-accurate encoders and decoders for `RGBA32`, `RGBA16` (5551), `IA16`, `IA8`, `IA4`, `I8`, `I4`, `CI8`, and `CI4`.
- **Dialogue Script & Hex Sanitizer (`miorom.formats.script_catalog`)**:
  - `DialogueCleaner`: Strips low-level pointer artifacts, garbage byte tags, and parses control codes to natural newlines.
  - `ScriptCatalog`: Bidirectional translation catalog manager in clean human-readable `[id]\ntext` format with synchronization back to CSV.
- **Universal Control Code Tokenizer (`miorom.text.tokenizer`)**:
  - Bidirectional serialization between binary control codes and markup tags (`ControlCodeSchema`, `ControlCodeTokenizer`, `ControlCodeDef`).
- **Far-Memory Layout Allocation (`miorom.patch.slack`)**:
  - `FarMemoryHeap`: Manages memory allocation in expanded ROM address spaces (e.g. 32 MB -> 64 MB) with alignment and boundary enforcement.
- **Constant-Memory Streaming Patcher (`miorom.patch.ips`)**:
  - `IpsPatcher.apply_stream()`: Stream-based chunked patching (<64 KB RAM) for multi-gigabyte disc images (Wii/GameCube/PS1).
- **Segmented Address Resolution (`miorom.core.pointer`)**:
  - `SegmentTable` and `SegmentedAddressResolver` for two-way translation of segmented virtual addresses (0x07xxxxxx, KSEG0, SNES banks) to physical ROM offsets.
- **N64 Audio & Sequences (`miorom.audio.n64_seq`)**:
  - `M64Sequence` (N64 Compact MIDI command parser) and `N64Audiobank` (instrument sample metadata).
- **Universal Save File Checksum Engine (`miorom.save.checksum`)**:
  - `SaveChecksumEngine.verify_and_fix()` supporting SRAM, EEPROM, and FlashRAM save files.
- **Symbol Table Interop (`miorom.core.symbol_map`)**:
  - Added export methods: `to_ghidra_script()` (Python Script Manager), `to_ida_idc()` (IDA Pro IDC), and `to_sym()` (No$GBA / PCSX symbol format).
- **Automated Function Boundary Detection (`miorom.asm.prologue_scanner`)**:
  - `FunctionPrologueScanner`: Bitmask preamble scanning for MIPS (`addiu $sp`), ARM (`push {lr}`), and PowerPC (`stwu r1`).
- **Proportional Font Kerning & Textbox Collision (`miorom.text.vwf`)**:
  - `VWFMetricsInspector`: Kerning pair tracking and automated dialogue overflow detection against textbox boundaries.
- **MIPS Compound Relocation Matching (`miorom.link.relocator`)**:
  - `CompoundRelocationLinker`: Proper sign-extension carry bit compensation for paired `R_MIPS_HI16` and `R_MIPS_LO16` relocations.
- **Native Color Quantization (`miorom.graphics.palette`)**:
  - `FloydSteinbergDitherer`: Pure-Python error-diffusion dithering for palette reduction without external dependencies.
- **Bytecode Interpreter Profiling (`miorom.script.vm_profiler`)**:
  - `VMBytecodeSynthesizer.detect_dispatcher_tables()`: Automated jump table discovery for custom virtual machine opcode interpreters.
- **Semantic Patch Safety Validation (`miorom.diff.patch_auditor`)**:
  - `PatchAuditor`: Validates IPS/BPS patch hunks against critical ROM memory regions (headers, DMA descriptors, vectors) to prevent asset collision.
- **Declarative Schema Constraints (`miorom.core.schema`)**:
  - `SchemaField(validate=...)`: Custom validation hooks on struct fields with structured `ParseError` exceptions.
- **Emulator Database Compatibility (`miorom.platforms.n64`)**:
  - Added `preserve_database_crc` parameter to `N64Rom.recalculate_checksum()` and `fix_n64_checksum()` to retain No-Intro database matching for emulator boxart and profiles.

### Changed
- Standardized `CsvHandler.export_csv()` and `export_clean_csv()` to automatically ensure parent directories exist before writing.
- Bumped version to `0.13.0`.


## [0.12.0] — Initial Release

- Core ROM hacking toolkit: scanning, patching, compression, disassembly, platform handlers.
