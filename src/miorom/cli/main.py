import argparse
import sys
import os

from miorom import __version__
from miorom.formats.batch import BatchSplitter, BatchMerger
from miorom.formats.csv_handler import CsvHandler
from miorom.text.wrapper import WordWrapper


def cmd_split(args):
    print(f"[*] Splitting {args.input_csv} into chunks of {args.size} rows...")
    files = BatchSplitter.split_csv(
        input_csv=args.input_csv,
        output_dir=args.output_dir,
        batch_size=args.size,
        prefix=args.prefix
    )
    print(f"[✓] Created {len(files)} batch files in '{args.output_dir}'!")


def cmd_merge(args):
    print(f"[*] Merging batch files from '{args.batch_dir}' -> '{args.output_csv}'...")
    count = BatchMerger.merge_dir(
        batch_dir=args.batch_dir,
        output_csv=args.output_csv,
        master_csv=args.master
    )
    print(f"[✓] Successfully merged {count} translations into '{args.output_csv}'!")


def cmd_validate(args):
    print(f"[*] Validating '{args.csv_file}' for text box overflow...")
    rows = CsvHandler.import_csv(args.csv_file)
    wrapper = WordWrapper(max_chars_per_line=args.max_chars, max_lines_per_box=args.max_lines)

    issues = 0
    for r in rows:
        text = r.translation if r.translation.strip() else r.original
        is_valid, warnings = wrapper.validate_textbox(text)
        if not is_valid:
            issues += 1
            print(f"[!] Row {r.index} (Offset {r.offset_hex}):")
            for w in warnings:
                print(f"    - {w}")

    if issues == 0:
        print("[✓] All rows passed textbox validation!")
    else:
        print(f"[!] Found {issues} rows with potential textbox overflow.")


def cmd_patch_create(args):
    print(f"[*] Creating patch: {args.original} -> {args.modified} ({args.output})...")
    from miorom.patch import create_patch
    create_patch(args.original, args.modified, args.output, fmt=args.format)
    size_kb = os.path.getsize(args.output) / 1024
    print(f"[✓] Successfully created patch: {args.output} ({size_kb:.2f} KB)!")


def cmd_patch_apply(args):
    print(f"[*] Applying patch: {args.original} + {args.patch} -> {args.output}...")
    from miorom.patch import apply_patch
    apply_patch(args.original, args.patch, args.output, fmt=args.format)
    size_mb = os.path.getsize(args.output) / (1024 * 1024)
    print(f"[✓] Successfully patched file: {args.output} ({size_mb:.2f} MB)!")


def cmd_compress(args):
    print(f"[*] Compressing '{args.input_file}' using {args.format.upper()}...")
    from miorom.compression import compress
    with open(args.input_file, "rb") as f:
        data = f.read()
    compressed = compress(data, fmt=args.format)
    with open(args.output, "wb") as f:
        f.write(compressed)
    orig_sz = len(data)
    comp_sz = len(compressed)
    ratio = (comp_sz / orig_sz * 100) if orig_sz > 0 else 0
    print(f"[✓] Compressed: {orig_sz} -> {comp_sz} bytes ({ratio:.1f}%) saved to '{args.output}'!")


def cmd_decompress(args):
    print(f"[*] Decompressing '{args.input_file}'...")
    from miorom.compression import decompress
    with open(args.input_file, "rb") as f:
        data = f.read()
    decompressed = decompress(data)
    with open(args.output, "wb") as f:
        f.write(decompressed)
    print(f"[✓] Decompressed: {len(data)} -> {len(decompressed)} bytes saved to '{args.output}'!")


def cmd_scan(args):
    print(f"[*] Scanning '{args.input_file}' for text and pointers...")
    from miorom.core.scanner import StringScanner, PointerScanner
    from miorom.formats.csv_handler import CsvHandler, TranslationRow

    with open(args.input_file, "rb") as f:
        data = f.read()

    # --- Deep format fingerprinting (optional) ---
    if args.deep:
        from miorom.scanner.deep import DeepScanner
        print("[*] Running deep format fingerprint scan...")
        report = DeepScanner().scan(data, min_confidence=0.5)
        if report.fingerprints:
            print(f"[✓] Detected {len(report.fingerprints)} known format(s):")
            for fp in report.fingerprints:
                print(f"    - 0x{fp.offset:06X}: [{fp.category}] {fp.format_name} "
                      f"(confidence: {int(fp.confidence*100)}%) — {fp.description}")
        else:
            print("[!] No known format signatures detected.")

    strings = StringScanner.scan_strings(
        data,
        min_length=args.min_len,
        encoding=args.encoding
    )
    print(f"[✓] Found {len(strings)} strings!")

    blocks = StringScanner.group_into_blocks(strings)
    print(f"[✓] Detected {len(blocks)} text block(s):")
    for i, b in enumerate(blocks[:10]):
        print(f"    - Block {i+1}: 0x{b.start_offset:06X} - 0x{b.end_offset:06X} ({b.count} strings, {b.total_bytes} bytes)")
    if len(blocks) > 10:
        print(f"    ... and {len(blocks) - 10} more text blocks.")

    if args.pointers:
        print("[*] Scanning for pointer tables...")
        offsets = [s.offset for s in strings]
        tables = PointerScanner.find_pointer_tables(data, offsets)
        if tables:
            print(f"[✓] Found {len(tables)} candidate pointer table(s):")
            for t in tables[:5]:
                print(f"    - Offset {t.table_offset_hex}: count={t.count}, stride={t.stride}, endian='{t.endian}', base={t.base_offset_hex} (confidence: {t.confidence:.2f})")
        else:
            print("[!] No obvious pointer tables detected.")

        # --- Footer pointer scan (Gap 1: dual-table formats) ---
        footer_tables = PointerScanner.find_footer_pointer_tables(
            data, offsets, footer_scan_bytes=args.footer_scan
        )
        # Filter: only show footer tables that are at different offset from Table1 tables
        t1_offsets = {t.table_offset for t in tables}
        footer_tables = [t for t in footer_tables if t.table_offset not in t1_offsets]
        if footer_tables:
            print(f"[⚠] Found {len(footer_tables)} footer/secondary pointer table(s) (dual-table format suspected):")
            for t in footer_tables:
                print(f"    - Offset {t.table_offset_hex}: count={t.count}, stride={t.stride}, endian='{t.endian}' (confidence: {t.confidence:.2f})")
                for entry_off, target in t.entries:
                    s_match = next((s for s in strings if s.offset == target), None)
                    preview = s_match.text[:40].replace("\n", "\\n") if s_match else "?"
                    print(f"      → entry@0x{entry_off:06X} → 0x{target:06X}: \"{preview}\"")
            print("[i] Hint: secondary tables often contain Yes/No choices or short stat labels.")

        if args.orphans:
            # Kumpulkan semua offset yang direferensi oleh SEMUA pointer tables (T1 + footer)
            referenced_offsets = set()
            for t in tables + footer_tables:
                for _, target in t.entries:
                    referenced_offsets.add(target)

            orphans = [s for s in strings if s.offset not in referenced_offsets]
            if orphans:
                hint = ("secondary/footer pointer table" if not footer_tables
                        else "unknown mechanism")
                print(f"[⚠] Found {len(orphans)} orphaned string(s) (not referenced by any detected pointer table):")
                for s in orphans[:20]:
                    preview = s.text[:60].replace("\n", "\\n")
                    print(f"    - 0x{s.offset:06X}: \"{preview}\"")
                if len(orphans) > 20:
                    print(f"    ... and {len(orphans) - 20} more orphaned strings.")
                print(f"[i] Hint: orphaned strings may be referenced by a {hint} not yet detected.")
            else:
                print("[✓] No orphaned strings found — all strings are referenced by at least one pointer table.")

    if args.output:
        rows = [
            TranslationRow(
                index=i+1,
                offset=s.offset,
                length=s.length,
                original=s.text,
                translation=""
            )
            for i, s in enumerate(strings)
        ]
        CsvHandler.export_csv(rows, args.output)
        print(f"[✓] Exported {len(rows)} dialogue strings to '{args.output}'!")


def cmd_pipeline(args):
    print(f"[*] Loading pipeline recipe from '{args.recipe_file}'...")
    from miorom.pipeline import PipelineRecipe
    recipe = PipelineRecipe.load_file(args.recipe_file)
    print(f"[*] Executing pipeline: {recipe.name} ({len(recipe.steps)} steps)...")
    recipe.execute()
    print("[✓] Pipeline execution finished successfully!")


def cmd_unpack(args):
    print(f"[*] Unpacking '{args.rom_file}' -> '{args.output_dir}'...")
    from miorom.rom import unpack_rom
    meta = unpack_rom(args.rom_file, args.output_dir, fmt=args.format)
    print(f"[✓] Successfully unpacked {meta.get('platform', 'ROM')} ({meta.get('format', '').upper()}) to '{args.output_dir}'!")
    if "title" in meta and meta["title"] != "Unknown":
        print(f"    - Title: {meta['title']}")
    if "file_count" in meta:
        print(f"    - Extracted Files: {meta['file_count']}")


def cmd_repack(args):
    print(f"[*] Repacking '{args.input_dir}' -> '{args.output_file}'...")
    from miorom.rom import repack_rom
    data = repack_rom(args.input_dir, output_path=args.output_file, fmt=args.format)
    size_mb = len(data) / (1024 * 1024)
    print(f"[✓] Successfully repacked ROM: '{args.output_file}' ({len(data)} bytes, {size_mb:.2f} MB)!")


def cmd_toc(args):
    from miorom.archive.toc_pair import TocPair

    if args.toc_command == "list":
        print(f"[*] Reading TOC pair: '{args.bin_file}' + '{args.dat_file}'...")
        toc = TocPair.load(args.bin_file, args.dat_file)
        max_show = args.limit if args.limit else 30
        print(toc.summary(max_entries=max_show))

    elif args.toc_command == "extract":
        print(f"[*] Extracting index {args.index} from '{args.dat_file}'...")
        toc = TocPair.load(args.bin_file, args.dat_file)
        data = toc.extract(args.index)
        with open(args.output, "wb") as f:
            f.write(data)
        entry = toc.get_entry(args.index)
        print(f"[✓] Extracted {len(data)} bytes (TOC entry: offset=0x{entry.offset:08X}, size={entry.size}) -> '{args.output}'")

    elif args.toc_command == "inject":
        print(f"[*] Injecting '{args.input_file}' -> index {args.index} in '{args.dat_file}'...")
        toc = TocPair.load(args.bin_file, args.dat_file)
        with open(args.input_file, "rb") as f:
            new_data = f.read()
        old_size = toc.get_entry(args.index).size
        out_bin = args.out_bin if args.out_bin else args.bin_file
        out_dat = args.out_dat if args.out_dat else args.dat_file
        toc.inject(args.index, new_data, out_bin=out_bin, out_dat=out_dat)
        delta = len(new_data) - old_size
        sign = "+" if delta >= 0 else ""
        print(f"[✓] Injected {len(new_data)} bytes at index {args.index} (size delta: {sign}{delta})")
        print(f"    TOC -> '{out_bin}', DAT -> '{out_dat}'")


def cmd_inspect(args):
    from miorom.scanner.inspector import SmartInspector
    with open(args.input_file, "rb") as f:
        data = f.read()
    report = SmartInspector.inspect(data, filepath=args.input_file)
    print(report.summary())


def cmd_init(args):
    from miorom.project.scaffold import ProjectScaffold
    dest = ProjectScaffold.generate(args.project_name, dest_dir=args.dest_dir, platform=args.platform)
    print(f"[✓] Project '{args.project_name}' successfully scaffolded in '{dest}'!")
    print(f"    - Edit '{os.path.join(dest, 'game.py')}' to declare your game assets.")
    print(f"    - Run 'miorom run {os.path.join(dest, 'game.py')} analyze' to begin.")


def cmd_run(args):
    import importlib.util
    from miorom.project.game import Game
    if not os.path.exists(args.game_py):
        print(f"[!] File not found: '{args.game_py}'")
        return
    spec = importlib.util.spec_from_file_location("game_module", args.game_py)
    if spec is None or spec.loader is None:
        print(f"[!] Could not load Python file: '{args.game_py}'")
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    game_cls = None
    for attr_name in dir(mod):
        val = getattr(mod, attr_name)
        if isinstance(val, type) and issubclass(val, Game) and val is not Game:
            game_cls = val
            break

    if not game_cls:
        print(f"[!] No Game subclass found in '{args.game_py}'.")
        return

    inst = game_cls()
    action = args.action.lower()
    if action == "analyze":
        inst.analyze()
    elif action == "extract":
        inst.extract(output_dir=args.output or "translations")
    elif action == "validate":
        inst.validate(translations_dir=args.translations or "translations")
    elif action == "build":
        inst.build(output_rom=args.output)
    else:
        print(f"[!] Unknown game action: '{action}'. Choose from: analyze, extract, validate, build.")


def cmd_cheat(args):
    print(f"[*] Generating cheat code from diff: {args.original} -> {args.modified}...")
    from miorom.asm.cheat import CheatCodeGenerator

    with open(args.original, "rb") as f:
        orig = f.read()
    with open(args.modified, "rb") as f:
        mod = f.read()

    base_addr = int(args.base, 16) if args.base.startswith("0x") or args.base.startswith("0X") else int(args.base)
    gen = CheatCodeGenerator.from_diff(orig, mod, base_address=base_addr, title=args.title)

    if args.type == "gecko":
        out_txt = gen.to_gecko(game_id=args.game_id)
    elif args.type == "ar":
        out_txt = gen.to_action_replay()
    elif args.type == "cwcheat":
        out_txt = gen.to_cwcheat(game_id=args.game_id)
    elif args.type == "gameshark":
        out_txt = gen.to_gameshark()
    else:
        out_txt = gen.to_gecko(game_id=args.game_id)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_txt + "\n")
        print(f"[✓] Cheat code saved to '{args.output}' ({len(gen.entries)} entries)!")
    else:
        print("\n" + out_txt + "\n")
        print(f"[✓] Total {len(gen.entries)} cheat code lines generated.")


def cmd_port_csv(args):
    print(f"[*] Porting translations from '{args.source_csv}' -> '{args.target_csv}' (Strategy: {args.strategy.upper()})...")
    from miorom.diff.porter import CrossRegionPorter
    from miorom.diff.mapper import BinaryDiffMapper

    mapper = None
    if args.strategy == "offset":
        if not args.source_bin or not args.target_bin:
            print("[!] Strategy 'offset' requires both --source-bin and --target-bin to correlate addresses.")
            return
        with open(args.source_bin, "rb") as f:
            b_src = f.read()
        with open(args.target_bin, "rb") as f:
            b_tgt = f.read()
        mapper = BinaryDiffMapper(b_src, b_tgt)
        mapper.find_matching_blocks()

    porter = CrossRegionPorter(diff_mapper=mapper)
    ported_rows, report = porter.port_csv(
        source=args.source_csv,
        target=args.target_csv,
        strategy=args.strategy,
        output_csv=args.output,
    )
    print(report.summary())
    if args.output:
        print(f"[✓] Ported translations exported to '{args.output}'!")

def cmd_port_patch(args):
    print(f"[*] Porting patch '{args.patch}' from '{args.from_file}' to '{args.to_file}'...")
    from miorom.diff.bindiff import BinDiffEngine
    from miorom.diff.mapper import BinaryDiffMapper
    from miorom.diff.porter import CrossRegionPorter

    def parse_address_list(raw: str) -> list:
        if not raw:
            return []
        return [int(item, 0) for item in raw.split(",") if item.strip()]

    with open(args.from_file, "rb") as file_handle:
        source_data = file_handle.read()
    with open(args.to_file, "rb") as file_handle:
        target_data = file_handle.read()
    with open(args.patch, "rb") as file_handle:
        patch_data = file_handle.read()

    source_funcs = parse_address_list(args.source_funcs)
    target_funcs = parse_address_list(args.target_funcs)
    if not source_funcs:
        source_funcs = BinDiffEngine.discover_function_candidates(
            source_data, args.source_base, endian=args.endian, limit=args.max_functions
        )
    if not target_funcs:
        target_funcs = BinDiffEngine.discover_function_candidates(
            target_data, args.target_base, endian=args.endian, limit=args.max_functions
        )

    bin_report = BinDiffEngine.diff_binaries(
        data_a=source_data,
        base_a=args.source_base,
        funcs_a=source_funcs,
        data_b=target_data,
        base_b=args.target_base,
        funcs_b=target_funcs,
        arch=args.arch,
        threshold=args.threshold,
    )
    print(bin_report.summary())

    porter = CrossRegionPorter()
    ported_patch, port_report = porter.port_patch(
        source_data=source_data,
        target_data=target_data,
        patch_data=patch_data,
        function_matches=bin_report.matches,
        source_base=args.source_base,
        target_base=args.target_base,
    )
    with open(args.output, "wb") as file_handle:
        file_handle.write(ported_patch)
    print(port_report.summary())
    print(f"[✓] Translated patch saved to '{args.output}' ({len(ported_patch)} bytes)!")

def cmd_inject_elf(args):
    print(f"[*] Linking and injecting ELF payload '{args.payload_elf}' into '{args.target_bin}'...")
    from miorom.link.injector import ElfInjector

    hook_addr = int(args.hook, 0) if args.hook else None
    hook_offset = int(args.hook_offset, 0) if args.hook_offset else None
    cave_addr = int(args.cave, 0) if args.cave else None
    cave_offset = int(args.cave_offset, 0) if args.cave_offset else None
    base_addr = int(args.base, 0) if args.base else 0

    out_file = args.output or args.target_bin

    patched_buf, report = ElfInjector.inject(
        target=args.target_bin,
        elf=args.payload_elf,
        hook_ram_addr=hook_addr,
        hook_file_offset=hook_offset,
        cave_ram_addr=cave_addr,
        cave_file_offset=cave_offset,
        ram_base=base_addr,
        external_symbols=args.symbols,
        entry_symbol=args.entry,
        arch=args.arch,
        hook_mode=args.hook_mode,
        output_file=out_file,
    )
    print(report.summary())
    print(f"[✓] Successfully injected payload into '{out_file}'!")


def main():
    argv = sys.argv
    parser = argparse.ArgumentParser(
        prog="miorom",
        description=f"MioROM: Modular ROM hacking & reverse engineering toolkit (v{__version__})"
    )
    parser.add_argument("-v", "--version", action="version", version=f"miorom {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    # Split command
    p_split = subparsers.add_parser("split", help="Split a master CSV into smaller batch files")
    p_split.add_argument("input_csv", help="Path to master CSV file")
    p_split.add_argument("-o", "--output-dir", default="batches", help="Output directory for batch CSVs")
    p_split.add_argument("-s", "--size", type=int, default=500, help="Number of rows per batch (default: 500)")
    p_split.add_argument("-p", "--prefix", default="batch", help="Filename prefix for batch files")

    # Merge command
    p_merge = subparsers.add_parser("merge", help="Merge multiple batch CSV files into a master CSV")
    p_merge.add_argument("batch_dir", help="Directory containing batch CSV files")
    p_merge.add_argument("-o", "--output-csv", required=True, help="Path to output merged CSV")
    p_merge.add_argument("-m", "--master", help="Optional original master CSV to fill untranslated rows from")

    # Validate command
    p_val = subparsers.add_parser("validate", help="Validate translation strings against textbox overflow constraints")
    p_val.add_argument("csv_file", help="Path to CSV file with translations")
    p_val.add_argument("-c", "--max-chars", type=int, default=32, help="Max characters per line (default: 32)")
    p_val.add_argument("-l", "--max-lines", type=int, default=3, help="Max lines per textbox (default: 3)")

    # Patch Create command
    p_pcreate = subparsers.add_parser("patch-create", help="Create an IPS, BPS, or Xdelta patch between original and modified ROM")
    p_pcreate.add_argument("original", help="Path to original / unmodified ROM/ISO")
    p_pcreate.add_argument("modified", help="Path to modified / translated ROM/ISO")
    p_pcreate.add_argument("-o", "--output", required=True, help="Path to output patch file (.xdelta, .bps, .ips)")
    p_pcreate.add_argument("-f", "--format", choices=["xdelta", "bps", "ips"], default="bps", help="Patch format (default: bps)")

    # Patch Apply command
    p_papply = subparsers.add_parser("patch-apply", help="Apply an IPS, BPS, or Xdelta patch to an original ROM")
    p_papply.add_argument("original", help="Path to original / unmodified ROM/ISO")
    p_papply.add_argument("patch", help="Path to patch file (.xdelta, .bps, .ips)")
    p_papply.add_argument("-o", "--output", required=True, help="Path to output patched ROM/ISO")
    p_papply.add_argument("-f", "--format", choices=["xdelta", "bps", "ips"], default=None, help="Force patch format")

    # Compress command
    p_comp = subparsers.add_parser("compress", help="Compress a file using Nintendo compression (LZ10, LZ11, RLE)")
    p_comp.add_argument("input_file", help="Path to uncompressed input file")
    p_comp.add_argument("-o", "--output", required=True, help="Path to output compressed file")
    p_comp.add_argument("-f", "--format", choices=["lz10", "lz11", "rle"], default="lz11", help="Compression algorithm (default: lz11)")

    # Decompress command
    p_decomp = subparsers.add_parser("decompress", help="Auto-detect and decompress Nintendo compressed file (LZ10, LZ11, RLE)")
    p_decomp.add_argument("input_file", help="Path to compressed input file")
    p_decomp.add_argument("-o", "--output", required=True, help="Path to output decompressed file")

    # Scan command
    p_scan = subparsers.add_parser("scan", help="Scan a binary file for dialogue strings, text blocks, and pointer tables")
    p_scan.add_argument("input_file", help="Path to binary file to scan")
    p_scan.add_argument("-e", "--encoding", default="ascii", help="Character encoding (default: ascii)")
    p_scan.add_argument("-m", "--min-len", type=int, default=4, help="Minimum string length (default: 4)")
    p_scan.add_argument("-p", "--pointers", action="store_true", help="Also scan for pointer tables referencing detected strings")
    p_scan.add_argument("--orphans", action="store_true", help="Report strings not referenced by any detected pointer table (requires --pointers)")
    p_scan.add_argument("--footer-scan", type=int, default=256, metavar="BYTES",
                        help="Size of footer window to scan for secondary pointer tables, in bytes (default: 256, requires --pointers)")
    p_scan.add_argument("--deep", action="store_true", help="Run deep format fingerprinting to identify known container formats (e.g., Neverland_FEFE, U8, NARC)")
    p_scan.add_argument("-o", "--output", help="Optional output CSV path to dump detected strings for translation")

    # Pipeline command
    p_pipe = subparsers.add_parser("pipeline", help="Execute an automated recipe workflow")
    p_pipe.add_argument("recipe_file", help="Path to JSON recipe file")

    # Unpack command
    p_unpack = subparsers.add_parser("unpack", help="Unpack a ROM or container (NDS, GameCube/Wii ISO, U8 ARC, NARC, ISO9660, Cartridge)")
    p_unpack.add_argument("rom_file", help="Path to input ROM or container file")
    p_unpack.add_argument("output_dir", help="Path to destination directory")
    p_unpack.add_argument("-f", "--format", choices=["nds", "gamecube", "u8", "narc", "iso9660", "cartridge"], default=None, help="Force container format")

    # Repack command
    p_repack = subparsers.add_parser("repack", help="Repack an unpacked directory back into a ROM image")
    p_repack.add_argument("input_dir", help="Path to directory containing unpacked ROM")
    p_repack.add_argument("output_file", help="Path to destination repacked ROM file")
    p_repack.add_argument("-f", "--format", choices=["nds", "gamecube", "u8", "narc", "iso9660", "cartridge"], default=None, help="Force container format")

    # TOC command (Gap 4: TOC binary pair handler)
    p_toc = subparsers.add_parser("toc", help="Operate on a TOC binary pair (.bin index + .dat payload)")
    p_toc.add_argument("bin_file", help="Path to .bin TOC index file")
    p_toc.add_argument("dat_file", help="Path to .dat payload file")
    toc_sub = p_toc.add_subparsers(dest="toc_command", help="TOC operation")

    # toc list
    p_toc_list = toc_sub.add_parser("list", help="List TOC entries")
    p_toc_list.add_argument("-n", "--limit", type=int, default=30, help="Max entries to show (default: 30)")

    # toc extract
    p_toc_ext = toc_sub.add_parser("extract", help="Extract a sub-file by index")
    p_toc_ext.add_argument("index", type=int, help="TOC entry index to extract")
    p_toc_ext.add_argument("-o", "--output", required=True, help="Output file path")

    # toc inject
    p_toc_inj = toc_sub.add_parser("inject", help="Inject (replace) a sub-file by index")
    p_toc_inj.add_argument("index", type=int, help="TOC entry index to replace")
    p_toc_inj.add_argument("input_file", help="Path to new sub-file to inject")
    p_toc_inj.add_argument("--out-bin", help="Output .bin path (default: overwrite original)")
    # Inspect command (Unified Smart Inspector)
    p_inspect = subparsers.add_parser("inspect", help="Smart inspection and reverse engineering diagnosis of a binary file")
    p_inspect.add_argument("input_file", help="Path to binary file to inspect")

    # Init command (Project Scaffolding)
    p_init = subparsers.add_parser("init", help="Scaffold a new ROM hacking project directory")
    p_init.add_argument("project_name", help="Name of the project")
    p_init.add_argument("-d", "--dest-dir", help="Destination directory (default: same as project name)")
    p_init.add_argument("-p", "--platform", default="wii", help="Platform name (default: wii)")

    # Run command (Game Framework Runner)
    p_run = subparsers.add_parser("run", help="Run a Game framework definition action (analyze, extract, validate, build)")
    p_run.add_argument("game_py", help="Path to game.py definition file")
    p_run.add_argument("action", choices=["analyze", "extract", "validate", "build"], help="Action to execute")
    p_run.add_argument("-o", "--output", help="Optional output path (for extract or build)")
    p_run.add_argument("-t", "--translations", help="Optional translations directory (for validate)")

    # Cheat command (Live RAM Cheat Code Generator)
    p_cheat = subparsers.add_parser("cheat", help="Generate live cheat codes (Gecko, AR, CWCheat, GameShark) from binary diff")
    p_cheat.add_argument("original", help="Path to original binary file")
    p_cheat.add_argument("modified", help="Path to modified binary file")
    p_cheat.add_argument("-t", "--type", choices=["gecko", "ar", "cwcheat", "gameshark"], default="gecko", help="Cheat format (default: gecko)")
    p_cheat.add_argument("-b", "--base", default="0x80000000", help="Base RAM address (default: 0x80000000)")
    p_cheat.add_argument("-o", "--output", help="Output file path (default: stdout)")
    p_cheat.add_argument("--title", default="MioROM Live Patch", help="Cheat code title")
    p_cheat.add_argument("--game-id", help="Optional Game ID header")

    # Port-CSV command (Cross-Region Translation Porter)
    p_port = subparsers.add_parser("port-csv", help="Migrate translations from source region CSV to target region CSV")
    p_port.add_argument("source_csv", help="Path to source translated CSV")
    p_port.add_argument("target_csv", help="Path to target untranslated CSV")
    p_port.add_argument("-o", "--output", required=True, help="Output ported CSV file path")
    p_port.add_argument("-s", "--strategy", choices=["index", "offset"], default="index", help="Matching strategy (default: index)")
    p_port.add_argument("--source-bin", help="Optional path to source binary for offset correlation")
    p_port.add_argument("--target-bin", help="Optional path to target binary for offset correlation")

    # Inject-ELF command (ELF C-Code Payload Linker & Injector)
    p_inj = subparsers.add_parser("inject-elf", help="Link and inject compiled C/ASM ELF payload into a game binary (DOL or raw ROM)")
    p_inj.add_argument("target_bin", help="Path to target binary (e.g. main.dol, arm9.bin, or raw dump)")
    p_inj.add_argument("payload_elf", help="Path to compiled ELF object file (.o / .elf)")
    p_inj.add_argument("-o", "--output", help="Path to output patched binary (default: overwrite target)")
    p_inj.add_argument("--hook", help="Hook RAM address to hijack (e.g. 0x80001234)")
    p_inj.add_argument("--hook-offset", help="Explicit hook file offset")
    p_inj.add_argument("--cave", help="Code cave RAM address (e.g. 0x80500000)")
    p_inj.add_argument("--cave-offset", help="Explicit code cave file offset")
    p_inj.add_argument("-b", "--base", default="0", help="Base RAM address for flat binaries (default: 0)")
    p_inj.add_argument("-s", "--symbols", help="Path to external symbol map file (.sym, .map, .json, .csv)")
    p_inj.add_argument("-e", "--entry", help="Payload entry function name (default: auto)")
    p_inj.add_argument("-a", "--arch", choices=["ppc", "arm", "thumb", "mips_le", "mips_be"], help="Architecture override")
    p_inj.add_argument("-m", "--hook-mode", choices=["trampoline", "call", "replace"], default="trampoline", help="Hook mode (default: trampoline)")

    # Port-Patch command (BinDiff-aware IPS migration)
    p_port_patch = subparsers.add_parser("port-patch", help="Translate an IPS patch between regional binary versions")
    p_port_patch.add_argument("--from", dest="from_file", required=True, help="Source-region binary (patch was made against this)")
    p_port_patch.add_argument("--to", dest="to_file", required=True, help="Target-region binary")
    p_port_patch.add_argument("--patch", required=True, help="Source-region IPS patch")
    p_port_patch.add_argument("-o", "--output", required=True, help="Output translated IPS patch")
    p_port_patch.add_argument("--source-base", type=lambda value: int(value, 0), default=0, help="Source function base address")
    p_port_patch.add_argument("--target-base", type=lambda value: int(value, 0), default=0, help="Target function base address")
    p_port_patch.add_argument("--source-funcs", help="Comma-separated source function addresses")
    p_port_patch.add_argument("--target-funcs", help="Comma-separated target function addresses")
    p_port_patch.add_argument("--endian", choices=["big", "little"], default="big", help="Pointer scan endian")
    p_port_patch.add_argument("--max-functions", type=int, default=256, help="Maximum auto-discovered functions")
    p_port_patch.add_argument("-a", "--arch", choices=["ppc", "arm", "thumb", "mips_le", "mips_be"], default="ppc", help="Lifter architecture")
    p_port_patch.add_argument("--threshold", type=float, default=0.75, help="BinDiff match threshold")

    args = parser.parse_args(argv[1:])

    if args.command == "split":
        cmd_split(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "patch-create":
        cmd_patch_create(args)
    elif args.command == "patch-apply":
        cmd_patch_apply(args)
    elif args.command == "compress":
        cmd_compress(args)
    elif args.command == "decompress":
        cmd_decompress(args)
    elif args.command == "scan":
        cmd_scan(args)
    elif args.command == "pipeline":
        cmd_pipeline(args)
    elif args.command == "unpack":
        cmd_unpack(args)
    elif args.command == "repack":
        cmd_repack(args)
    elif args.command == "toc":
        cmd_toc(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "cheat":
        cmd_cheat(args)
    elif args.command == "port-csv":
        cmd_port_csv(args)
    elif args.command == "port-patch":
        cmd_port_patch(args)
    elif args.command == "inject-elf":
        cmd_inject_elf(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
