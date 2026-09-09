# MioROM API Reference & Architecture Guide

MioROM v0.13.0 is an all-in-one modular Python framework for ROM hacking, fan translation engineering, and game reverse engineering.

### Companion Guides
- [Binary & Assembly Primitives Guide](BINARY_PRIMITIVES.md) - Low-level patching, micro-assembly, and struct serialization.
- [CLI Reference Manual](CLI_REFERENCE.md) - Complete command-line manual for terminal commands.
- [Console Platform & Format Reference](PLATFORMS.md) - Technical format specifications for NDS, Wii/GC, PS1, N64, GBA, SNES, and MD.
- [End-to-End Localization Workflow Guide](WORKFLOW_GUIDE.md) - 6-phase walkthrough from untouched ROM to distributed patch.
- [Library Contracts](LIBRARY_CONTRACTS.md) - Serialization, streaming, patch-structure, extensibility, and path-safety contracts for programmers building on MioROM.
- [Security Guide](SECURITY.md) - Handling untrusted ROMs/archives safely: path traversal (zip-slip) protection and extraction hardening.

---

## Module Index

### 1. Core & Memory Management (`miorom.core`)
| Class / Function | Description |
| :--- | :--- |
| `MioRomResult` | Serialization contract for public result objects (`to_dict()`, `from_dict()`, JSON round-trip). |
| `BinaryReader` | Big-endian / little-endian binary stream reader with safe seeking and padding. |
| `BinaryWriter` | Stream serializer with alignment support and patch generation. |
| `PointerTable` | Absolute, relative, and flagged pointer table manager with 1:1 relocation. |
| `PointerEntry` | Individual pointer abstraction with value, offset, and target tracking. |
| `SegmentTable` | Registry of hardware and virtual segment base addresses (N64 0x00..0x0F, PS1 KSEG0, SNES banks). |
| `SegmentedAddressResolver` | Two-way resolver translating segmented virtual addresses (e.g. `0x07001234`) to/from physical offsets. |
| `StringScanner` | Automatic text detector for UTF-8, Shift-JIS, UTF-16, and ASCII. |
| `StringScanner.iter_strings()` | Progressive string generator for `itertools` pipelines and early exit. |
| `PointerScanner` | Heuristic pointer table scanner pointing to discovered string blocks. |
| `PointerScanner.iter_pointer_tables()` | Progressive pointer-table generator for streaming scans. |
| `ByteOffsetMapper` | LCS-based 1:1 byte alignment mapper for expanded strings. |
| `RelocatableBuffer` | Pristine snapshotting memory buffer for safe chained patch commits. |
| `MemoryMap` | Segmented emulator and hardware address space mapper. |
| `SignatureScanner` | IDA/Ghidra-style wildcard byte pattern matcher (`"E1 A0 00 00 ?? ?? ?? 1A"`). |
| `BinaryStruct` | Declarative struct schema modeling (`U8`, `U16`, `U32`, `FixedString`, `Array`). |
| `BinaryStruct.sizeof_dynamic()` | Measures dynamic variable-length structs (PascalString, SentinelArray, If) from binary bytes. |
| `BinaryStruct.offset_of_dynamic()` | Resolves dynamic field offsets directly from bytes with structured `ParseError` on truncation. |
| `SchemaField(validate=...)` | Declarative validation hook enforcing logical field boundaries during parsing. |
| `MultiLevelPointerTable` | Hierarchical cascading pointer table dereferencer (Chapter -> Scene -> String). |
| `TableLevel` | Specification for a single level in a multi-level pointer table. |
| `RecordBuilder` | Fluent binary record and struct constructor with padding, strings, and alignment. |
| `SymbolMap` | Address and symbol notebook with No$GBA (.sym) and Ghidra CSV export/import. |
| `SymbolMap.to_ghidra_script()` | Exports symbol table as a runnable Ghidra Python Script. |
| `SymbolMap.to_ida_idc()` | Exports symbol table as an IDA Pro IDC script. |
| `SymbolMap.to_sym()` | Exports symbol table in standard No$GBA / PCSX emulator format. |
| `SymbolEntry` | Data record representing an annotated memory address symbol. |
| `HexDiffHighlighter` | Visual terminal diff renderer highlighting binary changes with ANSI color codes. |

---

### 2. Disassembly, Assembly & Static Analysis (`miorom.asm`)
| Class / Function | Description |
| :--- | :--- |
| `UniversalDisassembler` | Multi-arch disassembler for PowerPC, ARM32, Thumb, and MIPS without C dependencies. |
| `UniversalDisassembler` (MIPS/SM83/M68K) | Decodes MIPS COP1 float ops, Game Boy (SM83), and Sega Mega Drive (Motorola 68000). |
| `DisasmInstruction` | Decoded instruction object with mnemonic, operands, branch target, and raw bytes. |
| `FunctionPrologueScanner` | Automated function boundary detector using preamble bitmasks (`addiu $sp`, `push {lr}`, `stwu r1`). |
| `CodeDataDisambiguator` | Separates `CODE`, `JUMP_TABLE`, `RODATA`, `STRING`, and `PADDING` deterministically. |
| `DataFlowSlicer` | Backward program slicer resolving switch-case jump tables and indirect branches. |
| `JumpTable` | Reconstructed switch-case jump table with case targets. |
| `AsmSnippet` / `MipsSnippet` | Fluent micro-assembly generator for ARM, MIPS (`li`, `lw`, `sw`, `addu`, `subu`, `j`, `jal`), and SM83. |
| `CodeCaveFinder` | Scans executables for contiguous unused padding bytes (`0x00`/`0xFF`). |
| `TrampolineHook` | Generates 5-instruction trampoline hooks preserving original overwritten opcodes. |
| `PPCInstructionScanner` | Finds paired `lis` + `addi` split pointers in PowerPC Wii/GameCube binaries. |
| `MIPSInstructionScanner` | Finds paired `lui` + `addiu` split pointers in MIPS PS1/N64 binaries. |
| `CheatCodeGenerator` | Generates Gecko, Action Replay, CWCheat, and GameShark memory patch codes. |
| `AntiPiracyBypasser` | Scans and patches NDS cartridge checks, checksum loops, and PPC integrity branches. |
| `AsmSnippet` | Factory for fluent micro-assembly snippet emission (`AsmSnippet.arm()`, `AsmSnippet.mips()`). |
| `ArmSnippet` | Fluent ARM32 instruction sequence builder (push, pop, mov, add, sub, b, bl, bx, nop). |
| `MipsSnippet` | Fluent MIPS instruction sequence builder (lui, addiu, jr_ra, nop). |

---

### 3. Intermediate Representation & Scripting (`miorom.script`)
| Class / Function | Description |
| :--- | :--- |
| `BinaryLifter` | Lifts machine code instructions into compiler Micro-IR and decompiles to pseudo-C. |
| `IRFunction`, `IRBlock`, `IRInstruction` | SSA-form Intermediate Representation primitives. |
| `ScriptVM` | Declarative cutscene/event bytecode virtual machine (disassembler & assembler). |
| `MioScriptCompiler` | High-level script DSL compiler with structured `if-else`, loops, and function calls. |
| `ScriptArcheologist` | Inferred opcode signatures from raw bytecode streams to synthesize working VMs. |
| `ScriptDecompiler` | Reconstructs high-level AST (`IfStmt`, `WhileStmt`) from linear bytecode. |
| `ScriptAST`, `ScriptASTBuilder` | Abstract Syntax Tree engine for dialogue and cutscene scripts. |

---

### 4. Deep Forensics, Cryptanalysis & Synthesis (`miorom.scanner`, `miorom.diff`, `miorom.archive`)
| Class / Function | Description |
| :--- | :--- |
| `DmaTableArchive` | High-level abstraction for parsing, querying, extracting, and decompressing N64 DMA filesystems. |
| `DmaFileEntry` | Descriptor for individual DMA files with virtual/physical boundaries and compression status. |
| `CryptoScanner` | Scans for AES S-Boxes, MD5/SHA-1 constants, TEA delta (`0x9E3779B9`), and CRC32 tables. |
| `XRefAnalyzer`, `XRefGraph` | Bi-directional cross-reference analyzer with pointer tracing and Mermaid export. |
| `BinDiffEngine` | Compares binaries via CFG graph isomorphism and mnemonic cyclomatic similarity. |
| `PatchAuditor` | Validates IPS/BPS patch hunks against critical ROM memory regions (headers, DMA descriptors, vectors) to prevent asset collision. |
| `ArchiveSynthesizer` | Heuristic reverse-engineering for unknown archives; auto-generates Python parser code. |
| `DeepScanner`, `InspectionReport` | Automated container fingerprinting and Shannon entropy profiling. |

---

### 5. Runtime Injection & Memory Management (`miorom.link`, `miorom.rom`, `miorom.debug`)
| Class / Function | Description |
| :--- | :--- |
| `ElfInjector` | Injects compiled GCC C-code payloads (`.o`/`.elf`) into DOL or ROM caves. |
| `ElfRelocator` | Resolves PowerPC, ARM, and MIPS relocations (`ADDR32`, `ADDR16_LO`, `REL24`). |
| `DolBinary` | GameCube / Wii DOL executable header parser and memory segment injector. |
| `MioRomHeap` | Dynamic slab/buddy runtime heap allocator (`miorom_malloc`, `miorom_free`). |
| `RomLayoutExpander` | Physical ROM expander for GBA (32MB), NDS, and N64 (64MB) with CIC recalculation. |
| `RomAddressSanitizer` | Emulation shadow-memory bounds checker with guard redzones and use-after-free poisoning. |
| `SaveStateDiffHunter` | Differential memory snapshot fuzzer and multi-level pointer trail discovery. |
| `DolphinClient`, `DolphinMemoryMock` | Live memory bridge into running Dolphin Emulator via shared memory. |

---

### 6. Text, Typography & Localization (`miorom.text`, `miorom.helper`)
| Class / Function | Description |
| :--- | :--- |
| `CharMap` | Custom `.tbl` character table transcoder for 1-byte, 2-byte, and multi-byte encodings. |
| `CharMapMiner` | Statistical n-gram character matrix miner reconstructing unknown `.tbl` tables. |
| `TrieTranscoder` | High-performance greedy longest-prefix transcoder for complex DTE dictionaries. |
| `PixelWordWrapper` | True on-screen Variable Width Font (VWF) word-wrapper and boundary checker. |
| `FontMetrics` | Proportional character glyph width and kerning registry. |
| `TextboxSimulator` | Visual dialogue renderer rendering dialogue pages to PNG previews for QA. |
| `AutoPaginator` | Splits translated monologues into dialogue pages respecting textbox limits. |
| `PoHandler` | GNU gettext `.po` parser and exporter for Weblate, Crowdin, and Poedit. |
| `StringPoolBuilder` | Automated string pool generator with synchronized pointer table construction. |
| `CascadingRelocator` | Delta-shifts downstream binary chunks and updates direct and split pointers. |
| `TagConverter` | Two-way converter between raw hex control tags and human-readable tokens. |
| `DualTableHelper` | Neverland/Marvelous dual-table text archive extractor and bit-perfect builder. |
| `GameTextTemplate` | Bidirectional dialogue template engine with dynamic control tags and reverse extraction. |
| `DialogueCleaner` | Strips binary pointer noise, raw hex tags (`<XX>`), and converts control codes to natural newlines. |
| `ScriptCatalog` | Formats and parses translation catalogs in human-readable `[id]\ntext` format with two-way CSV synchronization. |
| `ControlCodeTokenizer` | Universal bidirectional serializer between binary control codes and clean markup tags (`<COLOR:0A>`, `<NL>`). |
| `ControlCodeSchema` | Declarative registry of game-specific control code specifications. |
| `VWFMetricsInspector` | Kerning-aware proportional text measurer and textbox collision validator. |

---

### 7. Platforms & Disc/ROM Containers (`miorom.platforms`, `miorom.rom`)
| Class / Function | Description |
| :--- | :--- |
| `RomManager` | Unified auto-detecting ROM unpacker and repacker. |
| `U8Archive` | Nintendo Wii/GC `.arc` / `.szs` archive unpacker and repacker with 32-byte alignment. |
| `TPLFile` | GameCube & Wii texture container decoder (CMPR, RGB5A3, RGBA8, IA8). |
| `BRFNTFont` | Official Wii BRFNT binary font reader and glyph width calculator. |
| `NDSRom` | Nintendo DS `.nds` ROM header, FAT table, ARM9/ARM7, and multilingual banner parser. |
| `NARCArchive` | Nintendo DS `.narc` file container packer and unpacker. |
| `NFTRFont` | Nintendo DS Nitro Font (`.nftr`) reader, serializer, and kerning editor. |
| `GameCubeDisc` | Raw optical disc (`.iso`/`.gcm`) reader, banner reader, and compliant repacker. |
| `FstInjector` | Native GameCube & Wii File System Table (FST) in-place file replacer. |
| `N64Rom` | N64 ROM converter (Big-Endian `.z64`, Little-Endian `.n64`, Byte-Swapped `.v64`) and CIC fixer. |
| `N64Rom.recalculate_checksum()` | Calculates IPL3 checksum; includes `preserve_database_crc=True` to retain emulator database metadata. |
| `N64TextureDecoder` / `N64TextureEncoder` | Fast3D texture codec for `RGBA32`, `RGBA16` (5551), `IA16`, `IA8`, `IA4`, `I8`, `I4`, `CI8`, and `CI4`. |
| `Fast3DParser` | Parses N64 microcode display lists (`G_SETTIMG`, `G_SETTILE`, `G_SETTILESIZE`, `G_LOADBLOCK`) to discover textures. |
| `Fast3DBuilder` | Fluent microcode emitter constructing N64 display lists directly in pure Python. |
| `FloydSteinbergDitherer` | Pure-Python error-diffusion dithering for palette reduction without external dependencies. |
| `M64Sequence` / `N64Audiobank` | Parser for Nintendo 64 Compact MIDI sequences (`.m64`) and audio instrument banks. |
| `SaveChecksumEngine` | Universal checksum validator and auto-repairer for SRAM (32KB), EEPROM, and FlashRAM save files. |
| `GBARom`, `GBRom` | Game Boy Advance and Game Boy ROM checksum verification and repair. |
| `MDRom` | Sega Mega Drive / Genesis ROM deinterleaver and checksum fixer. |
| `SNESRom` | Super Nintendo LoROM/HiROM header parser and checksum recalculator. |
| `PSXExe`, `TIMImage` | PlayStation 1 executable and TIM texture parser. |
| `ISO9660` | Standard CD-ROM ISO9660 filesystem parser and directory extractor. |
| `CueBinDisc` | Mixed-mode CD-ROM (BIN/CUE) disc image processor with EDC/ECC recalculation. |

---

### 8. Patching & Binary Modification (`miorom.patch`)
| Class / Function | Description |
| :--- | :--- |
| `IpsPatcher` | Standard IPS patch creator and applier (up to 16MB). |
| `IpsPatcher.apply_stream()` | Constant-memory streaming patcher (<64 KB RAM) for multi-gigabyte disc images without OOM. |
| `IpsPatcher.parse()` / `IpsPatcher.iter_records()` | Decodes an IPS file into `PatchHunk` objects instead of applying it blindly. |
| `BpsPatcher` | Standard BPS patch creator and applier with CRC32 verification. |
| `BpsPatcher.parse()` | Decodes a BPS delta stream into inspectable `PatchHunk` objects. |
| `XdeltaPatcher` | VCDIFF / Xdelta patch creator and applier for large optical disc ROMs. |
| `PatchWriter` | Fluent binary patch emitter & IPS generator with cursor tracking and range replacement. |
| `FarMemoryHeap` | Dedicated allocator for expanded ROM regions (32 MB -> 64 MB) with alignment and boundary tracking. |
| `PatchRecord` | Atomic replacement record storing offset, original bytes, and replacement bytes. |
| `PatchHunk` | Structured, serializable patch unit (`to_dict()`) shared by IPS and BPS parsing. |
| `merge_patches()` / `filter_hunks()` | Composition primitives for combining or selecting `PatchHunk` sequences before re-serializing. |

---

### 9. Pipeline Orchestration (`miorom.pipeline`)
| Class / Function | Description |
| :--- | :--- |
| `PipelineStep` | Base class for a single automated pipeline action (decompress, extract, checksum, patch, etc.). |
| `DecompressStep`, `CompressStep`, `ExtractArchiveStep`, `PackArchiveStep`, `FixChecksumStep`, `CreatePatchStep` | Built-in step implementations covering the common ROM-hacking pipeline actions. |
| `PipelineContext` | Shared, template-aware state object (`get()`/`set()`/`format_string()`) passed across steps. |
| `PipelineRecipe` | Declarative, JSON/dict-serializable sequence of steps (`to_dict()`/`from_dict()`). |
| `PipelineRecipe.register_step_type()` | Public API for registering custom `PipelineStep` subclasses for use in recipe JSON/dict, without touching the internal step registry. |
| `PipelineHook` | Subscriber interface with `before_step(step, context)` / `after_step(step, context, success)` for logging, progress reporting, or validation around any step. |

---

### 10. Security & Untrusted Input Handling (`miorom.security`)
| Class / Function | Description |
| :--- | :--- |
| `sanitize_extract_path()` | Resolves an archive-entry-supplied filename against an output directory and guarantees the result cannot escape it; raises `UnsafeArchivePathError` on path traversal / zip-slip attempts. |
| `UnsafeArchivePathError` | `MioromError` subclass raised when an archive/ROM entry name would write outside the intended extraction directory. |

See the [Security Guide](SECURITY.md) for the full threat model, usage
examples, and the checklist for custom `BaseRomHandler`/archive
implementations.
