# MioROM API Reference & Architecture Guide

MioROM v1.0.4 is an all-in-one modular Python framework for ROM hacking, fan translation engineering, and game reverse engineering.

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
| `BitReader` | Arbitrary bitstream reader supporting MSB-first and LSB-first bit ordering across byte boundaries (`read_bits()`, `read_signed_bits()`, `peek_bits()`, `skip_bits()`, `align_byte()`). |
| `BitWriter` | Arbitrary bitstream writer supporting MSB/LSB accumulation, signed integers, and byte padding (`write_bits()`, `write_signed_bits()`, `align_byte()`, `to_bytes()`). |
| `SNESBusMapper` | Pure mathematical 24-bit SNES bus address and ROM file offset mapper for LoROM (Mode 20), HiROM (Mode 21), and SMC headers. |
| `NESBusMapper` | Pure mathematical bus-to-offset mapper for NES NROM (16KB/32KB), MMC1, and MMC3 8KB PRG banking (Modes 0 and 1). |
| `GameBoyBusMapper` | Cartridge ROM file offset mapper for Game Boy Bank 0 and switchable banks with MBC1 translation quirks. |
| `RetroChecksum` | Pure-Python retro checksum algorithms: CRC-16 (CCITT, XMODEM, ARC, Modbus), pure IEEE 802.3 CRC32, Adler-32, Fletcher-16, Genesis 16-bit word sum, SNES complement pair, and Game Boy header/global checksums. |
| `VariableLengthIntCodec` | Codec for MIDI 7-bit continuation VLQ, unsigned/signed LEB128, SQLite 1-9 byte varint, and ZigZag encoding. Shortcuts: `encode_vlq()`, `decode_vlq()`, `encode_uleb128()`, `decode_uleb128()`, `encode_sleb128()`, `decode_sleb128()`. |
| `rol`, `ror`, `bit_reverse` | Pure-Python bitwise rotation (`rol`/`ror`), bit reversal (`bit_reverse8`/`16`/`32`), and nibble packing/swapping (`swap_nibbles`, `pack_nibbles`, `unpack_nibbles`). |
| `sign_extend`, `popcount`, `clz`, `ctz`, `bswap` | Immediate integer sign extension, population count (`popcount`), count leading zeros (`clz`), count trailing zeros (`ctz`), and word byte swaps (`bswap16`/`32`/`64`). |
| `CanonicalHuffmanTable`, `HuffmanNode` | Canonical Huffman tree builder and bit-level table encoder/decoder. Implements `build_huffman_tree()`, `extract_code_lengths()`, `generate_canonical_codes()`, and direct stream encoding/decoding via `BitReader` / `BitWriter`. |
| `BinarySlicer`, `find_free_blocks` | Zero-copy memoryview slice navigator (`BinarySlicer`), chunking stream (`chunk_bytes`), alignment boundary calculators (`align_up`, `align_down`, `pad_bytes`), and contiguous padding/code-cave block discovery (`find_free_blocks`). |
| `RingBuffer`, `LzssMatchFinder` | High-performance sliding window circular buffer (`RingBuffer`) with RLE overlapping copy support (`copy_lz_match`), and hash-chained longest-match finder (`LzssMatchFinder`) with window expiration pruning for proprietary LZ compression algorithms. |
| `calculate_entropy`, `sliding_entropy_scan` | Shannon entropy calculator (0.0 to 8.0 bits/byte), byte frequency histogram, Chi-squared randomness testing, and sliding-window scanner to discover embedded compressed/encrypted stream boundaries (`find_entropy_regions`). |
| `xor_bytes`, `rolling_xor`, `add_cipher` | Byte-level deobfuscation suite: multi-byte repeating XOR (`xor_bytes`), rolling-key stream cipher (`rolling_xor`), bitwise NOT (`invert_bytes`), Caesar byte-addition (`add_cipher`), and automated single-byte XOR key cracker (`crack_single_byte_xor`). |
| `combine_split_words`, `deinterleave_channels` | Split-bus memory reconstruction: merges separate low-byte, high-byte, and bank-byte arrays into 16/24-bit words (`combine_split_words`, `split_words`); demuxes and interleaves multi-channel byte streams (`deinterleave_channels`, `interleave_channels`). |
| `cumulative_offsets`, `delta_decode` | Pointer and table offset resolvers: converts length sequences into contiguous start offsets (`cumulative_offsets`, `offsets_to_lengths`), differential delta encoders/decoders (`delta_encode`, `delta_decode`), and base relative-to-absolute translations. |
| `PointerTableCandidate`, `find_pointer_tables` | Pointer table sequence & monotonic stride validator: unpacks/packs 16-bit, 24-bit, and 32-bit pointer words (`unpack_pointer`, `pack_pointer`, `unpack_pointers`, `pack_pointers`), verifies monotonic ordering (`verify_stride_monotonicity`, `calculate_monotonicity_ratio`), evaluates statistical metrics & confidence (`analyze_pointer_sequence`), remaps addresses (`remap_pointers`), and discovers candidate tables in raw binaries (`find_pointer_tables`). |
| `BankedPointer`, `SplitPointerTable` | Split-bank & dual-table far pointer relinker: resolves (bank, address) to/from ROM file offsets (`resolve_banked_to_offset`, `resolve_offset_to_banked`), reads/writes parallel dual tables (`read_split_pointer_table`, `write_split_pointer_table`) and 3-byte contiguous far arrays (`read_interleaved_pointer_table`, `write_interleaved_pointer_table`), and performs in-place banked table relocations (`relocate_banked_table`). |
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
| `CStructOverlay` | Interactive ANSI C / C99 struct layout parser compiling C code directly into binary byte layouts. |
| `CStructInstance` | Dynamic record instance with dot/dict access, serialization (`to_dict()`, `to_json()`), and pack capabilities. |
| `CField` | Field descriptor with byte offset, size, type name, array length, and nested struct support. |
| `SchemaField(validate=...)` | Declarative validation hook enforcing logical field boundaries during parsing. |
| `MultiLevelPointerTable` | Hierarchical cascading pointer table dereferencer (Chapter -> Scene -> String). |
| `TableLevel` | Specification for a single level in a multi-level pointer table. |
| `RecordBuilder` | Fluent binary record and struct constructor with padding, strings, and alignment. |
| `BitField`, `BitFieldCodec` | Sub-byte bitfield and packed record codec: defines arbitrary bit-width schemas (1 to 64 bits), signed two's complement fields, MSB/LSB bit ordering, in-place buffer mutation (`pack_into()`), and tabular array processing (`unpack_all()`). |
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
| `UniversalDisassembler` | Multi-arch disassembler for 8 architectures: PowerPC, ARM32, Thumb-16, MIPS I-IV / COP1, Game Boy (SM83), Motorola 68000, MOS 6502 (NES), and W65C816 (SNES with dynamic REP/SEP tracking). |
| `DisasmInstruction` | Decoded instruction object with mnemonic, operands, branch target, and raw bytes. |
| `SymbolicXrefEngine` | Cross-architecture static analyzer discovering symbolic cross-references (ARM, Thumb, PPC, MIPS, W65C816, MOS6502). |
| `XRefDatabase` | Bidirectional index of code and data cross-references (`xrefs_to()`, `xrefs_from()`, `callers_of()`, `annotate_disassembly()`). |
| `XRefRecord` | Rich cross-reference link with source/target addresses, symbols, and instruction metadata. |
| `FunctionPrologueScanner` | Automated function boundary detector using preamble bitmasks (`addiu $sp`, `push {lr}`, `push {r4-r7, lr}`, `stwu r1`, `php; rep #$xx; pha`). |
| `CodeDataDisambiguator` | Separates `CODE`, `JUMP_TABLE`, `RODATA`, `STRING`, and `PADDING` deterministically. |
| `DataFlowSlicer` | Backward program slicer resolving switch-case jump tables and indirect branches. |
| `JumpTable` | Reconstructed switch-case jump table with case targets. |
| `AsmSnippet` | Factory for fluent micro-assembly snippet emission: `.arm()`, `.thumb()`, `.mips()`, `.ppc()`, `.sm83()`, `.snes()`. |
| `ArmSnippet` | Fluent ARM32 instruction sequence builder (push, pop, mov, add, sub, b, bl, bx, nop). |
| `ThumbSnippet` | Fluent 16-bit ARM Thumb instruction sequence builder for GBA & NDS (push, pop, mov, add, sub, cmp, ldr, str, b, b_cond, bl, bx, blx, nop). |
| `MipsSnippet` | Fluent MIPS instruction sequence builder (lui, addiu, li, lw, sw, jr_ra, j, jal, nop). |
| `PpcSnippet` | Fluent PowerPC 32-bit instruction sequence builder for GC & Wii (stwu, lwz, stw, addi, li, lis, ori, mr, mflr, mtlr, b, bl, blr, nop). |
| `SM83Snippet` | Fluent Game Boy SM83 instruction sequence builder (ld, push, pop, call, ret, jr, jp, cb, rst). |
| `SnesSnippet` | Fluent W65C816 instruction sequence builder for SNES (rep, sep, clc, sec, pha, pla, lda, sta, ldx, stx, ldy, sty, jsr, jsl, rts, rtl, bra). |
| `CodeCaveFinder` | Scans executables for contiguous unused padding bytes (`0x00`/`0xFF`). |
| `CodeCaveManager` | Tracking and allocation registry for ROM free-space blocks with automated candidate scanning. |
| `ArmHookBuilder` | Pure bitwise instruction builder for ARM `BL`/`B`, Thumb `BL` (4-byte), Thumb `B`, and return trampolines. |
| `HookManager` | Coordinates inline hook placement at call sites and trampoline assembly in target code caves. |
| `M68kDisassembler` | Motorola 68000 instruction disassembler covering data, arithmetic, branch, and control opcodes. |
| `M68kInstruction` | Decoded M68K instruction record with size, branch targets, call identification, and listing formatting. |
| `calc_arm_branch`, `calc_thumb_branch` | Low-level mathematical branch opcode calculators and resolvers for 32-bit ARM (B, BL with 8-byte prefetch pipeline compensation) and 16-bit Thumb (dual-hword BL/BLX pair with 4-byte pipeline compensation). |
| `calc_mips_jump`, `calc_mips_branch`, `calc_6502_branch` | Target calculation primitives for MIPS 26-bit pseudo-absolute jumps (J, JAL), MIPS 16-bit word-offset branches with delay slot calculation, and MOS 6502 / W65C816 8-bit signed relative branches. |
| `BranchRelocator`, `BranchRelocation` | PC-relative branch displacement rebasing engine for MOS 6502, W65C816, Z80, SM83, M68K, ARM, Thumb, and MIPS; recalculates relative jumps when relocating routines to code caves and discriminates internal vs external branch destinations (`rebase_block()`, `patch_single_branch()`). |
| `TrampolineHook` | Generates multi-architecture trampoline hooks (MIPS, ARM, Thumb, MOS 6502, W65C816 SNES JML/JSL) preserving original opcodes. |
| `VWFHookConfig` | Declarative configuration for VWF hook deployment: architecture, hook ROM/RAM addresses, original instruction bytes, glyph width table source, optional explicit cave address, fallback width, character range, and endianness. |
| `VWFDeploymentReport` | Full audit trail of a VWF hook deployment: hook record, table ROM/RAM offset and size, lookup routine ROM/RAM offset and size, total code cave bytes consumed, and verification status (`to_dict()` for logging). |
| `VWFHookEngine` | End-to-end VWF hook orchestrator: verifies hook site integrity (`verify_hook_site()`), generates architecture-specific width lookup routines (`synthesize_width_routine()` for ARM32, Thumb, MIPS32, SNES W65C816, MOS 6502), and atomically deploys width table + trampoline into a ROM code cave (`deploy()` with `simulate=True` dry-run mode). |
| `PPCInstructionScanner` | Finds paired `lis` + `addi` split pointers in PowerPC Wii/GameCube binaries. |
| `MIPSInstructionScanner` | Finds paired `lui` + `addiu` split pointers in MIPS PS1/N64 binaries. |
| `CheatCodeGenerator` | Generates Gecko, Action Replay, CWCheat, and GameShark memory patch codes. |
| `AntiPiracyBypasser` | Scans and patches NDS cartridge checks, checksum loops, and PPC integrity branches. |

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
| `ScriptExtractor` | Bidirectional ROM script extraction and reinserter supporting TXT/CSV serialization and dry-run validation. |
| `ExtractionResult`, `ExtractedEntry` | Structured container holding extracted script entries, offsets, raw bytes, and control code tags. |
| `InsertionReport` | Diagnostic summary of script reinsertion with inserted counts and overflow warnings. |
| `detect_delimiters`, `detect_control_codes` | Script delimiter & control code auto-detector: discovers 1-byte/multi-byte string terminators across pointer boundaries (`detect_delimiters`), identifies embedded bytecode opcodes and estimates parameter arguments (`detect_control_codes`), generates `ScriptBoundaryReport` (`analyze_script_boundaries`), and extracts cleanly bounded script entries (`slice_script_entries`). |
| `DialogueDissector`, `DialogueBlock` | Automated ROM dialogue pointer table scanner and extractor: maps console base addresses, extracts dialogue blocks to GNU gettext `.po` or JSON, and reinjects translated text with automatic free-space relocation (`scan_dialogue_tables()`, `reinject_dialogues()`). |
| `VMOpcodeType` | Enumeration of VM instruction categories: `TEXT`, `BRANCH_REL`, `BRANCH_ABS`, `SWITCH`, `CONTROL`, and `TERMINATOR`. |
| `VMInstructionDef` | Opcode schema definition carrying opcode byte, mnemonic, type, fixed length, text terminator, length-prefix flag, declarative `schema` (`SchemaField` / `BinaryStruct`), and legacy operand format string. |
| `DissectedInstruction` | Fully decoded script instruction: index, ROM offset, byte length, opcode, raw bytes, text payload, branch target, relative delta, switch targets, and operand offset. |
| `DissectedScriptVM` | Disassembled script container with instruction list and base offset; provides `get_dialogues()` for dialogue extraction and `to_po()` for GNU gettext PO export. |
| `ScriptVMDissector` | Linear sweep bytecode disassembler for arbitrary opcode schemas (`disassemble()`); dynamic text replacement and relinking engine that rewrites translated strings and recalculates all relative branch deltas, absolute jump targets, and switch tables in-place using declarative `BinaryStruct` schemas (`splice_and_relink()`). |


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
| `TextStreamScanner`, `TextStreamSpan` | Multi-byte Japanese binary text stream scanner: strict lead-byte and trail-byte FSM validation for Shift-JIS, EUC-JP, UTF-16LE, UTF-16BE, and ASCII; filters machine code false positives, computes confidence metrics, and detects contiguous string tables (`scan()`, `scan_string_table()`). |
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
| `JapaneseCharmap` | Multi-byte character encoding handler supporting Shift-JIS and EUC-JP with bidirectional dakuten and handakuten composition/decomposition. |
| `TrieTranscoder` | High-performance greedy longest-prefix transcoder for complex DTE dictionaries. |
| `WordWrapper` | Fixed-width character-count word-wrapper and textbox dimension validator (`miorom.text.line_wrapper`). |
| `PixelWordWrapper` | True on-screen Variable Width Font (VWF) word-wrapper and boundary checker (`miorom.text.line_wrapper`). |
| `FontMetrics` | Proportional character glyph width and kerning registry (`miorom.text.line_wrapper`). |
| `VwfLineWrapper`, `AdaptiveLineWrapper` | Pixel-accurate VWF word-wrapper and paginator accepting dicts, binary table bytes, callables, `FontGlyphInjector`, or `FontMetrics` instances. Preserves game control codes (`[wait]`, `{hero}`, `<color:red>`) during line measurement. |
| `LineWrapResult`, `TextBoxPage` | Structured results containing paginated dialogue pages, per-line pixel widths, and overflow diagnostics. |
| `DTEMiner`, `DTEToken` | Dual-Tile and Multi-Tile Encoding (DTE/MTE) frequency miner and token dictionary builder (`miorom.text.dte`). |
| `DteOptimizer`, `DteCodec` | DTE/MTE n-gram frequency optimizer and greedy two-way transcoder integrated with `CharMap` for net-savings dictionary compression. |
| `DteStats`, `DteEntry` | Result dataclasses for dictionary compression metadata (bytes saved, ratio, per-token frequency). |
| `TagManager`, `TagSyntaxValidator` | Complete markup control tag lifecycle suite: bidirectional code-to-tag conversion, bracket balance verification, and translation variable fidelity checks (`miorom.text.tags`). |
| `TagValidationReport` | Structured diagnostic report of tag syntax validity, unmatched brackets, and missing game variables. |
| `TextDialoguePipeline` | End-to-end dialogue translation pipeline integrating table discovery, tokenization, line wrapping, and relocation (`miorom.text.pipeline`). |
| `PointerRelinker` | Scans pointer tables (1..4 bytes, big/little-endian) and updates targets, auto-relocating overflowing strings to ROM free space. |
| `PointerRecord`, `RelinkReport` | Structured records for discovered pointers and relinking operation diagnostics. |
| `TranslationMemory` | In-memory translation memory leveraging pure-Python Levenshtein distance for exact (100%) and fuzzy matching. |
| `TmLookupResult`, `TmMatch` | Translation memory search candidate records with similarity scoring. |
| `BMFont` | AngelCode BMFont parser and serializer supporting both Text and XML formats with automatic atlas shelf packing. |
| `PNGCodec` | Built-in 100% pure-Python minimal PNG encoder and decoder (grayscale & RGBA) using only standard library `zlib`. |
| `PlanarTileCodec` | Pure-Python planar bitplane and chunky 8x8 tile codec (1bpp, 2bpp GB/NES/SNES, 3bpp Capcom SNES, 4bpp SNES planar, 4bpp Genesis chunky, 4bpp GBA, 8bpp Mode 7). Supports `split_bitplanes()`, `combine_bitplanes()`, `planar_to_linear()`, and `linear_to_planar()`. |
| `Tilemap`, `TilemapEntry` | Multi-console tilemap & nametable matrix compositor: supports NES nametables + 64B attribute tables (`decode_nes_nametable`, `encode_nes_nametable`), Sega Genesis VDP Plane 16-bit (`decode_genesis_tilemap`, `encode_genesis_tilemap`), GBC dual VRAM banks (`decode_gbc_tilemap`, `encode_gbc_tilemap`), 2D/1D pixel compositing (`render_pixels`), and rectangular submap slicing/pasting. |
| `Metatile16`, `MetatileTable`, `MetatileMap` | Metatile 16x16 / 32x32 assembly and level map expansion engine: sequential 8-bit/16-bit and planar 4-array metatile definition table codecs, bidirectional 2D level map ↔ 8x8 tilemap expansion (`to_tilemap()`) and compression (`from_tilemap()`). |
| `TileDeduplicator`, `TileDedupResult` | 8x8 tile deduplication and VRAM optimizer: eliminates duplicate tiles, matches symmetrical H-flip, V-flip, and HV-flip copies, and generates remapped nametable words for SNES, Genesis, GBC, and GBA (`deduplicate()`, `deduplicate_raw_bpp()`). |
| `HardwareOamCodec`, `SpriteDescriptor` | Multi-platform hardware sprite Object Attribute Memory (OAM) descriptor codec: decodes and encodes sprite tables for NES (4-byte), Game Boy / GBC (4-byte), SNES (split Table 1 + Hi-OAM Table 2), Sega Genesis (8-byte SAT), and GBA (8-byte OAM). |
| `FontGlyphInjector` | Console font glyph injector and Latin extender (1bpp/2bpp/4bpp) with VWF binary width table generator and .tbl mapping export. |
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
| `JapaneseWordMatch` | Single kanji/kana word match record: byte offset, decoded string, charmap key bytes, confidence score, and character class flags (hiragana, katakana, kanji). |
| `JapaneseMiningCluster` | Grouped cluster of consecutive gojūon-row matches with density scoring and overall confidence. |
| `JapaneseCharMapMiner` | Relative search engine discovering game-specific Japanese character encodings by mining hiragana/katakana gojūon rows with dakuten variants; auto-generates draft `.tbl` files (`auto_generate_tbl()`). |
| `FontGeometry` | Glyph bounding box record (left, top, right, bottom, advance_width) derived from planar tile pixel data. |
| `DissectedGlyph` | Single dissected glyph: tile index, raw pixel bytes, geometry, and is-blank flag. |
| `WidthTableCandidate` | Candidate VWF width table discovered in a ROM buffer: offset, byte-width per entry, and advance width histogram. |
| `FontCandidate` | Font bank candidate: ROM offset, glyph count, tile format, bit-depth, glyph list, and optional width table. |
| `FontDissector` | Heuristic font bank scanner combining entropy scoring, stroke fill density, and glyph diversity checks (`scan_font_banks()`); discovers adjacent VWF width tables (`scan_width_tables()`); renders glyph PNG spritesheets (`export_sheet_png()`); injects replacement glyphs and width tables back into ROM buffers (`inject_glyphs()`, `inject_width_table()`). |
| `HuffmanNodeEntry` | Single node in an array-based binary Huffman tree: left child index, right child index, symbol value, and is-leaf flag. |
| `HuffmanTreeCandidate` | Discovered Huffman tree: ROM offset, node count, depth, symbol set, and decoded bitstream payload for content verification. |
| `DteDictionaryCandidate` | Discovered DTE bigram table: ROM offset, entry count, active (non-dummy) bigrams, byte coverage, and uniqueness ratio. |
| `TextCompressionHunter` | Retro text compression forensics: discovers Huffman trees via root-0 traversal without hardcoded node-count assumptions (`scan_huffman_trees()`), parses arbitrary-sized array-based trees (`parse_huffman_tree_auto()`), decompresses bitstreams (`decompress_huffman()`), scans DTE bigram tables (`scan_dte_tables()`), and re-encodes translated text with an optimal Huffman pass (`compress_huffman()`). |

---

### 7. Platforms & Disc/ROM Containers (`miorom.platforms`, `miorom.rom`)
| Class / Function | Description |
| :--- | :--- |
| `RomManager` | Unified auto-detecting ROM unpacker and repacker. |
| `NESRom`, `NESHeaderStruct` | Nintendo Entertainment System iNES & NES 2.0 ROM parser, mapper detector, and PRG/CHR splitter. |
| `U8Archive` | Nintendo Wii/GC `.arc` / `.szs` archive unpacker and repacker with 32-byte alignment. |
| `TPLFile` | GameCube & Wii texture container decoder (CMPR, RGB5A3, RGBA8, IA8). |
| `BRFNTFont` | Official Wii BRFNT binary font reader and glyph width calculator. |
| `NDSRom` | Nintendo DS `.nds` ROM header, FAT table, ARM9/ARM7, and multilingual banner parser. |
| `NDSOverlayTable` | Two-way binary serializer for Nintendo DS ARM9 (`y9.bin`) and ARM7 (`y7.bin`) overlay table entries; supports add, update, and RAM address relocation per overlay ID. |
| `NDSOverlayCompressor` | LZ10 detection, decompression, and re-compression for NDS overlays with automatic compressed flag management. |
| `NDSOverlayManager` | High-level orchestrator for extracting, replacing, and relocating ARM9/ARM7 overlay payloads within `NDSRom`; auto-expands ROM buffer when replacement data exceeds original capacity. |
| `OverlayAllocationReport` | Structured result recording old/new RAM size, file size delta, and compression state for an overlay replacement operation. |
| `NARCArchive` | Nintendo DS `.narc` file container packer and unpacker. |
| `NFTRFont` | Nintendo DS Nitro Font (`.nftr`) reader, serializer, and kerning editor. |
| `NCLRFile` | Nintendo DS Nitro Color Palette (`.nclr`) file reader, serializer, and BGR555 palette editor. |
| `NCGRFile` | Nintendo DS Nitro Character Graphic (`.ncgr`) 2D tile graphic reader, raw tile unpacker, and builder. |
| `NSCRFile` | Nintendo DS Nitro Screen Resource (`.nscr`) tilemap screen layout reader and serializer. |
| `GameCubeDisc` | Raw optical disc (`.iso`/`.gcm`) reader, banner reader, and compliant repacker. |
| `FstInjector` | Native GameCube & Wii File System Table (FST) in-place file replacer. |
| `DolFile` | GameCube & Wii DOL executable parser and serializer with up to 7 text and 11 data sections. Supports bidirectional RAM↔file offset translation, direct `read_memory()`/`write_memory()`, and section injection (`add_section()`, `allocate_code_cave()`). |
| `N64Rom` | N64 ROM converter (Big-Endian `.z64`, Little-Endian `.n64`, Byte-Swapped `.v64`) and CIC fixer. |
| `N64Rom.recalculate_checksum()` | Calculates IPL3 checksum; includes `preserve_database_crc=True` to retain emulator database metadata. |
| `convert_endianness()` | In-memory N64 ROM byte-order converter accepting enum or string aliases (`"z64"`, `"v64"`, `"n64"`, `"big"`, `"little"`). |
| `convert_file_endianness()` | Streaming chunked N64 ROM file endianness converter with minimal memory usage. |
| `N64TextureDecoder` / `N64TextureEncoder` | Fast3D texture codec for `RGBA32`, `RGBA16` (5551), `IA16`, `IA8`, `IA4`, `I8`, `I4`, `CI8`, and `CI4`. |
| `Fast3DParser` | Parses N64 microcode display lists (`G_SETTIMG`, `G_SETTILE`, `G_SETTILESIZE`, `G_LOADBLOCK`) to discover textures. |
| `Fast3DBuilder` | Fluent microcode emitter constructing N64 display lists directly in pure Python. |
| `FloydSteinbergDitherer` | Pure-Python error-diffusion dithering for palette reduction without external dependencies. |
| `M64Sequence` / `N64Audiobank` | Parser for Nintendo 64 Compact MIDI sequences (`.m64`) and audio instrument banks. |
| `SaveChecksumEngine` | Universal checksum validator and auto-repairer for SRAM (32KB), EEPROM, and FlashRAM save files. |
| `GBARom` | Game Boy Advance cartridge ROM engine: header parsing, hardware complement checksum, Nintendo logo repair, RTC detection, SRAM patching, 1-64MB expansion/trimming, 32-bit pointer relinking, and BIOS SWI scanning. |
| `GBARomHandler` | ROM handler for Game Boy Advance (`.gba`) cartridges with unpack/repack and metadata manifest support. |
| `fix_gba_checksum`, `resolve_gba_region` | Helper functions for GBA header complement checksum repair and territory code resolution. |
| `create_synthetic_gba_rom` | Synthetic Game Boy Advance ROM fixture generator for isolated unit testing. |
| `GBRom`, `GBHeader`, `GBRomBuilder` | Game Boy / GBC cartridge header parser, multi-bank ROM builder with power-of-two capacity expansion, and checksum repair. |
| `calculate_header_checksum`, `calculate_global_checksum` | Pure-Python bitwise checksum recalculators for Game Boy ROM images. |
| `MDRom` | Sega Mega Drive / Genesis ROM deinterleaver and checksum fixer. |
| `SNESRom` | Super Nintendo LoROM/HiROM header parser and checksum recalculator. |
| `PSXRom`, `PSXFormat` | PlayStation 1 optical disc engine supporting 2048-byte Mode 1 ISO and 2352-byte Mode 2 Form 1 BIN with bit-exact 32-bit EDC recalculation, `SYSTEM.CNF` editing, VFS operations, and CUE generation. |
| `PSXRomHandler` | ROM handler for PlayStation 1 (`.iso`, `.bin`, `.cue`) disc images. |
| `PSXExe`, `TIMImage` | PlayStation 1 executable and TIM texture parser. |
| `PSPRom`, `PSPFormat`, `PSPRomHandler` | Unified PlayStation Portable disc and package ROM engine supporting ISO, CSO, and PBP with in-memory format conversion and VFS. |
| `PRXModule`, `PSPNIDResolver` | Sony PSP relocatable MIPS executable inspector, stub hooker, and SDK NID function resolver. |
| `AT3Audio`, `AT3Codec` | Sony PSP ATRAC3 and ATRAC3plus audio stream parser, BGM loop point editor, and WAV exporter. |
| `ISO9660` | Standard CD-ROM ISO9660 filesystem parser and directory extractor. |
| `Iso9660Builder` | Pure-Python ISO 9660 disc image synthesizer and directory tree builder. |
| `CSOImage` | Compressed ISO (CSO/CISO) sector-based random-access reader and block compressor. |
| `PBPFile` | Sony PlayStation Portable EBOOT.PBP container unpacker and repacker for all 8 canonical sections. |
| `SFOFile` | Sony PARAM.SFO (System File Object) metadata parser and serializer (UTF-8, ASCII, uint32). |
| `Palette`, `Color` | Universal palette manager with BGR555, Genesis 9-bit RGB333, Adobe ACT, and JASC-PAL conversions. |
| `GBASwiResolver` | Official Game Boy Advance BIOS SWI lookup database, instruction annotator, and binary scanner. |
| `GBAMultiboot` | GBA Multiboot (.mb) 256KB EWRAM program synthesizer, validator, and header parser. |
| `SaturnDiscHeader` | Sega Saturn 512-byte Sector 0 security bootstrap header parser, serializer, and region unlocker. |
| `DreamcastIpBin` | Sega Dreamcast 32KB IP.BIN bootstrap sector parser, CRC16 calculator, and region unlocker. |
| `GDISheet`, `GDITrack` | Sega Dreamcast GD-ROM descriptor sheet parser and high-density track locator. |
| `CueBinDisc` | Mixed-mode CD-ROM (BIN/CUE) disc image processor with EDC/ECC recalculation. |
| `WiiDisc`, `WBFSDisc` | Comprehensive Nintendo Wii optical disc (.iso / .wii) and WBFS container engine; supports DVD-5 / DVD-9, lazy AES-128-CBC cluster decryption (<50MB RAM), H0-H3 hash verification, FST file injection, and Trucha bug fake-signing. |
| `WiiRomHandler` | Automated `RomManager` handler for Nintendo Wii disc images (.iso, .wii, .wbfs) with partition unpacking and repacking. |
| `BTIImage` | Nintendo Binary Texture Image (`.bti`) parser, builder, and GX texture converter (CMPR, RGB565, RGB5A3, RGBA8, I4/I8, IA4/IA8) with mipmaps and LOD control. |
| `RARCArchive`, `RARCEntry` | Nintendo GameCube and Wii RARC resource archive (`.arc`, `.rarc`) parser, directory tree extractor, and builder with 16-bit filename hashing. |
| `BRRESFile`, `TEX0Image`, `PLT0Palette` | Nintendo Wii Binary Revolution Resource container (`.brres`) parser and injector with Patricia trie directory index groups (`BresIndexGroup`) and raw texture/palette management. |
| `RelFile`, `DolBinary` | Nintendo Wii / GC Relocatable Module (`.rel`) parser, linker, and runtime patcher resolving PowerPC relocation chains (`R_PPC_ADDR32`, `R_PPC_ADDR16_LO`, `R_PPC_ADDR16_HA`, `R_PPC_REL24`). |
| `GameCubeRomHandler` | Automated `RomManager` handler for Nintendo GameCube optical disc images (.iso, .gcm). |
| `RVZImage`, `RVZBuilder` | Dolphin RVZ compressed optical disc image container parser and decompressor with chunk hash validation. |
| `WiiBanner`, `GCBanner` | GameCube and Wii channel banner (`opening.bnr`) title, description, and graphic icon editor across Japanese and Western languages. |
| `BRLANFile`, `BRLYTFile` | Nintendo Wii Binary Revolution Layout screen (`.brlyt`) and animation (`.brlan`) editor for UI localization. |
| `BRSARArchive`, `BRSTMFile` | Nintendo Wii sound archive (`.brsar`) extractor and multi-channel DSP-ADPCM streaming audio engine (`.brstm`). |
| `THPVideo` | Nintendo GameCube and Wii cinematic movie demuxer extracting MJPEG frames and multi-channel DSP-ADPCM audio. |
| `RiivolutionEngine` | Runtime XML patch generator and validator for SD/USB Nintendo Wii disc modding. |
| `WADFile`, `WADTicket`, `WADTmd` | Nintendo Wii WAD installation package parser, unpacker, AES-128 cryptor, and TMD/ticket validator with Trucha bug fake-signing. |
| `MSBFFile` | Nintendo Message Flowchart Binary (`.msbf` / `FLW2`) branch and dialogue decision graph editor. |
| `MSBTFile` | Official Nintendo Message Studio Binary Text (`.msbt`) parser and builder with label hashing, ATR1 message attributes, and control code preservation. |
| `BMGFile` | Nintendo Binary Message pool (`.bmg`) parser and serializer for GameCube and Wii titles. |
| `NCERFile`, `NCERCell` | Nintendo DS Nitro Character Resource (`.ncer`) cell bank assembler and 2D sprite composite renderer. |
| `NANRFile`, `NANRSequence` | Nintendo DS Nitro Animation Resource (`.nanr`) sprite keyframe sequencer and timeline editor. |
| `STRMFile` | Nintendo DS Nitro Stream (`.strm`) streaming audio parser, encoder, and decoder (PCM8, PCM16, IMA-ADPCM) to standard WAV. |
| `SWARFile`, `SWAVEntry` | Nintendo DS Sound Wave Archive (`.swar`) extractor and rebuilder with loop point and sample rate preservation. |
| `NitroAssetCatalog`, `NitroSceneGraph` | High-level NDS 2D scene graph linking NCGR, NCLR, NSCR, NCER, and NANR files into animated scene previews. |
| `NSBMDFile`, `NSBTXFile` | Official Nintendo DS 3D model container (`.nsbmd`) and texture archive (`.nsbtx`) parser and in-place texture replacer. |
| `NDSBanner` | Nintendo DS cartridge banner parser and editor with multilingual titles and animated icon frames. |
| `BLZ` | Pure-Python backward LZSS decompressor and compressor for Nintendo DS ARM9 payloads. |
| `NDSRomHandler` | Automated `RomManager` handler for Nintendo DS (`.nds`) cartridge ROMs. |
| `PSXMemoryCard`, `PSXSaveFile` | Sony PlayStation 1 Memory Card manager (128 KB `.mcr`, `.mcd`, `.sav`) and single save blocks (`.mcs`) with 16-frame directory management, XOR checksums, and animated 16x16 4bpp save icon export. |
| `StrDemuxer` | PlayStation 1 raw CD sector stream (`.str`) demuxer for MDEC video bitstreams and CD-XA audio. |
| `GIMImage` | Sony PlayStation Portable GIM (`.gim`) texture parser, serializer, and PNG converter. |
| `psp_swizzle`, `psp_unswizzle` | Sony PSP Graphic Engine (GE) hardware VRAM swizzler/unswizzler organizing pixel scanlines into 16-byte blocks. |

---

### 8. Patching & Binary Modification (`miorom.patch`)
| Class / Function | Description |
| :--- | :--- |
| `IpsPatcher` | Standard IPS patch creator and applier (up to 16MB). |
| `IpsPatcher.apply_stream()` | Constant-memory streaming patcher (<64 KB RAM) for multi-gigabyte disc images without OOM. |
| `IpsPatcher.parse()` / `IpsPatcher.iter_records()` | Decodes an IPS file into `PatchHunk` objects instead of applying it blindly. |
| `BpsPatcher` | Standard BPS patch creator and applier with CRC32 verification. |
| `BpsPatcher.parse()` | Decodes a BPS delta stream into inspectable `PatchHunk` objects. |
| `UpsPatcher` | Universal Patching System (UPS) creator and applier with XOR diffing, VLQ encoding, and CRC32 verification. |
| `PPFPatcher` | PlayStation Patch Format (PPF v1, v2, v3) creator, in-memory patcher, and streaming disc applier. |
| `XdeltaPatcher` | VCDIFF / Xdelta patch creator and applier for large optical disc ROMs. |
| `PatchWriter` | Fluent binary patch emitter & IPS generator with cursor tracking and range replacement. |
| `FarMemoryHeap` | Dedicated allocator for expanded ROM regions (32 MB -> 64 MB) with alignment and boundary tracking. |
| `PatchRecord` | Atomic replacement record storing offset, original bytes, and replacement bytes. |
| `PatchHunk` | Structured, serializable patch unit (`to_dict()`) shared by IPS and BPS parsing. |
| `merge_patches()` / `filter_hunks()` | Composition primitives for combining or selecting `PatchHunk` sequences before re-serializing. |
| `NesGameGenie`, `SnesGameGenie`, `GenesisGameGenie`, `GameBoyGameGenie` | Platform-specific Game Genie cheat code decoders and encoders. |
| `GameShark` | GameShark / Action Replay `XXXXXXXX YYYY` cheat decoder for GBA, N64, and PS1. |
| `parse_cheat_code()` | Auto-detecting cheat string resolver; produces `CheatCode` records without requiring explicit platform. |
| `hard_patch_rom()` | Permanently injects a cheat by resolving CPU addresses to ROM file offsets (NES, SNES LoROM, Game Boy), validating compare bytes, and writing atomically. |
| `CheatCode` | Structured cheat code record carrying address, value, size, compare byte, and source string. |

---

### 9. Audio Codecs & Exporters (`miorom.audio`)
| Class / Function | Description |
| :--- | :--- |
| `VAGFile`, `VAGCodec`, `VAGHeader` | Sony PS1 & PS2 SPU-ADPCM audio format parser, 16-byte block encoder, decoder, and direct WAV exporter. |
| `BRRCodec` | Super Nintendo (SNES) SPC700 / S-DSP Bit Rate Reduction 9-byte audio block encoder and decoder with 4-filter interpolation and WAV export. |
| `SpcFile`, `SpcHeader` | SNES SPC700 sound file (`.spc`) parser and serializer; reads 64KB RAM, 128-byte S-DSP register block, and ID666 metadata. Provides `list_samples()`, `extract_brr_sample()`, `dump_samples_to_wav()`, and direct RAM read/write. |
| `DSPADPCMCodec` | Nintendo GameCube & Wii DSP-ADPCM 8-byte frame audio decoder and WAV converter. |
| `ADPCMCodec` | Standard IMA-ADPCM decoder and 16-bit PCM RIFF/WAVE file builder. |
| `WavCodec`, `WavSound` | Pure-Python zero-dependency RIFF WAVE audio container parser and 16-bit signed PCM encoder. |
| `CdXaDecoder` | PlayStation CD-XA ADPCM audio sector demuxer and WAV builder. |
| `SDATContainer`, `SSEQSequence` | Nintendo DS Sound Data archive and sequence parser. |

---

### 10. Compression Codecs (`miorom.compression`)
| Class / Function | Description |
| :--- | :--- |
| `Yay0` | Nintendo 64 / GameCube Yay0 3-stream LZSS decompressor and compressor. |
| `Yaz0` | Standard Nintendo Yaz0 decompressor and compressor. |
| `APLib` | Pure-Python aPLib decompressor and compressor with raw stream and AP32 container support. |
| `RefPack` | Electronic Arts RefPack / QFS decompressor and compressor. |
| `LZSS` | Standard Haruhiko Okumura 4096-byte sliding window LZSS decompressor and compressor. |
| `LZ10`, `LZ11` | Nintendo BIOS LZ77 type 0x10 and 0x11 decompressors and compressors. |
| `BLZ` | Pure-Python backward LZSS (BLZ) decompressor and in-place compressor for Nintendo DS ARM9 binaries and overlays. |
| `RLE` | Nintendo BIOS Run-Length Encoding (0x30) decompressor and compressor; supports 3 to 130 byte compressed runs and extended 32-bit headers. |
| `Huffman` | Nintendo BIOS Huffman 4-bit and 8-bit tree decompressor and compressor. |
| `decompress()`, `compress()` | Unified auto-detecting compression dispatcher by magic bytes or codec name. |

---

### 11. Pipeline Orchestration (`miorom.pipeline`)
| Class / Function | Description |
| :--- | :--- |
| `PipelineStep` | Base class for a single automated pipeline action (decompress, extract, checksum, patch, etc.). |
| `DecompressStep`, `CompressStep`, `ExtractArchiveStep`, `PackArchiveStep`, `FixChecksumStep`, `CreatePatchStep` | Built-in step implementations covering the common ROM-hacking pipeline actions. |
| `PipelineContext` | Shared, template-aware state object (`get()`/`set()`/`format_string()`) passed across steps. |
| `PipelineRecipe` | Declarative, JSON/dict-serializable sequence of steps (`to_dict()`/`from_dict()`). |
| `PipelineRecipe.register_step_type()` | Public API for registering custom `PipelineStep` subclasses for use in recipe JSON/dict, without touching the internal step registry. |
| `PipelineHook` | Subscriber interface with `before_step(step, context)` / `after_step(step, context, success)` for logging, progress reporting, or validation around any step. |

---

### 12. Security & Untrusted Input Handling (`miorom.security`)
| Class / Function | Description |
| :--- | :--- |
| `sanitize_extract_path()` | Resolves an archive-entry-supplied filename against an output directory and guarantees the result cannot escape it; raises `UnsafeArchivePathError` on path traversal / zip-slip attempts. |
| `UnsafeArchivePathError` | `MioromError` subclass raised when an archive/ROM entry name would write outside the intended extraction directory. |

See the [Security Guide](SECURITY.md) for the full threat model, usage
examples, and the checklist for custom `BaseRomHandler`/archive
implementations.

---

### 13. Graphics & Hardware Video Primitives (`miorom.graphics`)
| Class / Function | Description |
| :--- | :--- |
| `PlanarTileCodec` | Multi-format planar tile codec: 1bpp, 2bpp (Game Boy/NES), 3bpp, 4bpp planar (SNES), 4bpp linear (Genesis/GBA), and 8bpp. Decodes and encodes raw byte buffers into indexed pixel matrices. |
| `TileDeduplicator` | VRAM optimizer identifying exact duplicates and symmetrical flipped copies (horizontal, vertical, and HV-flip) across 8x8 tile sequences. Produces `TileDedupResult` with nametable mapping words for SNES, Sega Genesis, Game Boy Color, and GBA. |
| `DeduplicatedTileEntry` | Mapping entry relating an original tile index to unique optimized tile index, carrying flip flags and format converters (`to_nametable_word_snes()`, `to_nametable_word_genesis()`, `to_gbc_map_entry()`, `to_gba_map_entry()`). |
| `HardwareOamCodec` | Multi-platform hardware sprite attribute codec supporting NES (4-byte), Game Boy / GBC (4-byte), SNES dual split tables (Table 1 + Hi-OAM Table 2), Sega Genesis (8-byte SAT), and GBA (8-byte OAM). |
| `SpriteDescriptor` | Normalized 2D hardware sprite representation (`x`, `y`, `tile_id`, `palette`, `flip_h`, `flip_v`, `priority`, `size_flag`, `vram_bank`). |
| `TilemapDecoder` / `Tilemap` | 2D tilemap reader and compositor with scrolling, nametable translation, and VRAM layout simulation. |
| `TilemapTextRun` | Contiguous tile run record: row/col origin, direction, decoded text string, palette bank, flip flags, available padding count; JSON-serializable (`to_dict()`, `from_dict()`). |
| `TilemapMenuBox` | Rectangular menu region descriptor enclosing a list of `TilemapTextRun` items with parent-relative bounding box coordinates. |
| `TilemapDissector` | Menu layout dissector for fan translation tilemap work: scans horizontal/vertical text runs (`scan_text_runs()`), renders 2D ASCII grid for proofreading (`export_text_grid()`), injects translated labels with left/center/right alignment and boundary guards (`splice_label()`), extracts menu box text runs (`extract_menu_box()`), and provides full JSON layout round-trip (`export_layout_json()`, `import_layout_json()`) plus batch apply (`apply_layout_dict()`). |
| `PaletteTable` | Multi-platform color palette conversion (BGR555, RGB565, NES color indices) to and from 24-bit RGB tuples. |
| `MetaTileSystem` | Hierarchical 16x16 / 32x32 metatile compositor translating coarse level blocks into 8x8 hardware tile layouts. |
| `PngCodec` | Pure-Python zero-dependency PNG image encoder and decoder with support for RGBA32, RGB24, and Grayscale modes. |
