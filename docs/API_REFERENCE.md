# MioROM API Reference & Architecture Guide

MioROM v0.12.0 is an all-in-one modular Python framework for ROM hacking, fan translation engineering, and game reverse engineering.

### Companion Guides
- [Binary & Assembly Primitives Guide](BINARY_PRIMITIVES.md) - Low-level patching, micro-assembly, and struct serialization.
- [CLI Reference Manual](CLI_REFERENCE.md) - Complete command-line manual for terminal commands.
- [Console Platform & Format Reference](PLATFORMS.md) - Technical format specifications for NDS, Wii/GC, PS1, N64, GBA, SNES, and MD.
- [End-to-End Localization Workflow Guide](WORKFLOW_GUIDE.md) - 6-phase walkthrough from untouched ROM to distributed patch.

---

## Module Index

### 1. Core & Memory Management (`miorom.core`)
| Class / Function | Description |
| :--- | :--- |
| `BinaryReader` | Big-endian / little-endian binary stream reader with safe seeking and padding. |
| `BinaryWriter` | Stream serializer with alignment support and patch generation. |
| `PointerTable` | Absolute, relative, and flagged pointer table manager with 1:1 relocation. |
| `PointerEntry` | Individual pointer abstraction with value, offset, and target tracking. |
| `StringScanner` | Automatic text detector for UTF-8, Shift-JIS, UTF-16, and ASCII. |
| `PointerScanner` | Heuristic pointer table scanner pointing to discovered string blocks. |
| `ByteOffsetMapper` | LCS-based 1:1 byte alignment mapper for expanded strings. |
| `RelocatableBuffer` | Pristine snapshotting memory buffer for safe chained patch commits. |
| `MemoryMap` | Segmented emulator and hardware address space mapper. |
| `SignatureScanner` | IDA/Ghidra-style wildcard byte pattern matcher (`"E1 A0 00 00 ?? ?? ?? 1A"`). |
| `BinaryStruct` | Declarative struct schema modeling (`U8`, `U16`, `U32`, `FixedString`, `Array`). |
| `MultiLevelPointerTable` | Hierarchical cascading pointer table dereferencer (Chapter -> Scene -> String). |
| `TableLevel` | Specification for a single level in a multi-level pointer table. |
| `RecordBuilder` | Fluent binary record and struct constructor with padding, strings, and alignment. |
| `SymbolMap` | Address and symbol notebook with No$GBA (.sym) and Ghidra CSV export/import. |
| `SymbolEntry` | Data record representing an annotated memory address symbol. |
| `HexDiffHighlighter` | Visual terminal diff renderer highlighting binary changes with ANSI color codes. |

---

### 2. Disassembly, Assembly & Static Analysis (`miorom.asm`)
| Class / Function | Description |
| :--- | :--- |
| `UniversalDisassembler` | Multi-arch disassembler for PowerPC, ARM32, Thumb, and MIPS without C dependencies. |
| `DisasmInstruction` | Decoded instruction object with mnemonic, operands, branch target, and raw bytes. |
| `CodeDataDisambiguator` | Separates `CODE`, `JUMP_TABLE`, `RODATA`, `STRING`, and `PADDING` deterministically. |
| `DataFlowSlicer` | Backward program slicer resolving switch-case jump tables and indirect branches. |
| `JumpTable` | Reconstructed switch-case jump table with case targets. |
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
| `CryptoScanner` | Scans for AES S-Boxes, MD5/SHA-1 constants, TEA delta (`0x9E3779B9`), and CRC32 tables. |
| `XRefAnalyzer`, `XRefGraph` | Bi-directional cross-reference analyzer with pointer tracing and Mermaid export. |
| `BinDiffEngine` | Compares binaries via CFG graph isomorphism and mnemonic cyclomatic similarity. |
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
| `BpsPatcher` | Standard BPS patch creator and applier with CRC32 verification. |
| `XdeltaPatcher` | VCDIFF / Xdelta patch creator and applier for large optical disc ROMs. |
| `PatchWriter` | Fluent binary patch emitter & IPS generator with cursor tracking and range replacement. |
| `PatchRecord` | Atomic replacement record storing offset, original bytes, and replacement bytes. |
