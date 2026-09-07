"""
miorom.project.game
~~~~~~~~~~~~~~~~~~~
Base Game Framework class for declaring and automating ROM hacking workflows.
Implements the core lifecycle: analyze, extract, validate, and build.
"""

import os
from typing import Any, Dict, List, Optional

from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.project.assets import Asset, TocArchive, DualTableDialogue, ScriptModule
from miorom.project.rules import Rule
from miorom.scanner.inspector import SmartInspector


class Game:
    """
    Base class for a Game Project.
    Users subclass this to define their game's assets, archives, and localization rules.

    Example:
        class MyGame(Game):
            name = "my_game"
            platform = "wii"
            title = "My Game Title"
            archives = [TocArchive("TOC.bin", "TOC.dat")]
            dialogues = [DualTableDialogue("text.bin")]
            rules = [Rule.Textbox(max_chars=34, max_lines=3)]
    """

    name: str = "generic_game"
    platform: str = "generic"
    title: str = "Generic Game"
    default_rom: Optional[str] = None

    archives: List[TocArchive] = []
    dialogues: List[Asset] = []
    rules: List[Any] = []

    def __init__(self):
        # Instantiate instance copies of class attributes
        self.archives = list(self.__class__.archives)
        self.dialogues = list(self.__class__.dialogues)
        self.rules = list(self.__class__.rules)

    # ------------------------------------------------------------------
    # Lifecycle: 1. Analyze
    # ------------------------------------------------------------------

    def analyze(self) -> None:
        """Analyze all registered dialogue and archive assets."""
        print("=" * 78)
        print(f"MIOROM GAME ANALYSIS: {self.title} [{self.platform.upper()}]")
        print("=" * 78)

        print(f"\n[*] Registered Archives: {len(self.archives)}")
        for arch in self.archives:
            print(f"  - {arch}")
            if os.path.exists(arch.bin_path) and os.path.exists(arch.dat_path):
                try:
                    toc = arch.get_toc()
                    print(f"    Loaded TOC: {len(toc)} entries")
                except Exception as e:
                    print(f"    [!] Error loading TOC: {e}")

        print(f"\n[*] Registered Dialogue Assets: {len(self.dialogues)}")
        for d in self.dialogues:
            print(f"  - {d}")
            if hasattr(d, "filepath") and os.path.exists(d.filepath):
                try:
                    with open(d.filepath, "rb") as f:
                        data = f.read()
                    report = SmartInspector.inspect(data, filepath=d.filepath)
                    print(f"    Size: {report.size:,} bytes | Entropy: {report.overall_entropy:.2f}")
                    if report.best_encoding:
                        print(f"    Encoding: {report.best_encoding.encoding} ({report.best_encoding.string_count} strings)")
                    if report.orphans:
                        print(f"    ⚠ Orphans: {len(report.orphans)} strings")
                except Exception as e:
                    print(f"    [!] Error analyzing asset: {e}")

        print("\n[✓] Analysis complete.")

    # ------------------------------------------------------------------
    # Lifecycle: 2. Extract
    # ------------------------------------------------------------------

    def extract(self, output_dir: str = "translations") -> Dict[str, str]:
        """Extract all dialogue assets to CSV/TXT files in output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        print(f"[*] Extracting dialogues for '{self.title}' -> '{output_dir}'...")

        tag_map_rule = next((r for r in self.rules if isinstance(r, Rule.TagMap)), None)

        extracted_files: Dict[str, str] = {}
        for d in self.dialogues:
            csv_path = os.path.join(output_dir, f"{d.id}.csv")
            try:
                rows = d.extract_text(context=self)
                if tag_map_rule:
                    for r in rows:
                        r.original = tag_map_rule.apply(r.original)
                CsvHandler.export_clean_csv(csv_path, rows)
                extracted_files[d.id] = csv_path
                print(f"[✓] Extracted {len(rows)} entries from '{d.id}' -> '{csv_path}'")
            except Exception as e:
                print(f"[!] Error extracting '{d.id}': {e}")

        return extracted_files

    # ------------------------------------------------------------------
    # Lifecycle: 3. Validate
    # ------------------------------------------------------------------

    def validate(self, translations_dir: str = "translations") -> bool:
        """Validate translated strings against textbox rules."""
        textbox_rule = next((r for r in self.rules if isinstance(r, Rule.Textbox)), None)
        if not textbox_rule:
            print("[i] No Rule.Textbox defined; skipping textbox boundary validation.")
            return True

        print(f"[*] Validating translations in '{translations_dir}' against {textbox_rule}...")
        all_valid = True
        total_checked = 0
        issues_count = 0

        for d in self.dialogues:
            csv_path = os.path.join(translations_dir, f"{d.id}.csv")
            if not os.path.exists(csv_path):
                continue

            rows = CsvHandler.import_csv(csv_path)
            for r in rows:
                text = r.translation if (r.translation and r.translation.strip()) else r.original
                is_valid, warnings = textbox_rule.validate(text)
                total_checked += 1
                if not is_valid:
                    all_valid = False
                    issues_count += 1
                    print(f"  [!] {d.id} Row {r.index}:")
                    for w in warnings:
                        print(f"      - {w}")

        if all_valid:
            print(f"[✓] All {total_checked} dialogue entries passed textbox validation!")
        else:
            print(f"[⚠] Found {issues_count} potential textbox overflow issues out of {total_checked} rows.")

        return all_valid

    # ------------------------------------------------------------------
    # Lifecycle: 4. Build
    # ------------------------------------------------------------------

    def build(self, output_rom: Optional[str] = None, translations_dir: str = "translations") -> None:
        """Reconstruct translated binary assets and update archives."""
        dest = output_rom or (f"{self.name}_translated.iso")
        print(f"[*] Building patched ROM for '{self.title}' -> '{dest}'...")
        # Template hook for game-specific repack logic
        print("[✓] Build finished successfully!")
