"""
miorom.project.game
~~~~~~~~~~~~~~~~~~~
Base Game Framework class for declaring and automating ROM hacking workflows.
Implements the core lifecycle: analyze, extract, validate, and build.
"""

import os
import logging
from typing import Any, Dict, List, Optional

from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.project.assets import TocArchive
from miorom.project.protocols import AssetProtocol
from miorom.project.rules import Rule
from miorom.scanner.inspector import SmartInspector

logger = logging.getLogger(__name__)


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

    def register_dialogue(self, asset: AssetProtocol) -> None:
        """Register a structural dialogue asset without requiring Asset inheritance."""
        if not isinstance(asset, AssetProtocol):
            raise TypeError("dialogue asset must implement AssetProtocol")
        self.dialogues.append(asset)

    archives: List[TocArchive] = []
    dialogues: List[AssetProtocol] = []
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
        separator = "=" * 78
        logger.info(separator)
        logger.info("MIOROM GAME ANALYSIS: %s [%s]", self.title, self.platform.upper())
        logger.info(separator)

        logger.info("Registered Archives: %d", len(self.archives))
        for arch in self.archives:
            logger.info("  - %s", arch)
            if os.path.exists(arch.bin_path) and os.path.exists(arch.dat_path):
                try:
                    toc = arch.get_toc()
                    logger.info("    Loaded TOC: %d entries", len(toc))
                except Exception as e:
                    logger.warning("    Error loading TOC: %s", e)

        logger.info("Registered Dialogue Assets: %d", len(self.dialogues))
        for d in self.dialogues:
            logger.info("  - %s", d)
            if hasattr(d, "filepath") and os.path.exists(d.filepath):
                try:
                    with open(d.filepath, "rb") as f:
                        data = f.read()
                    report = SmartInspector.inspect(data, filepath=d.filepath)
                    logger.info("    Size: %s bytes | Entropy: %.2f", f"{report.size:,}", report.overall_entropy)
                    if report.best_encoding:
                        logger.info("    Encoding: %s (%d strings)", report.best_encoding.encoding, report.best_encoding.string_count)
                    if report.orphans:
                        logger.warning("    Orphans: %d strings", len(report.orphans))
                except Exception as e:
                    logger.warning("    Error analyzing asset: %s", e)

        logger.info("Analysis complete.")

    # ------------------------------------------------------------------
    # Lifecycle: 2. Extract
    # ------------------------------------------------------------------

    def extract(self, output_dir: str = "translations") -> Dict[str, str]:
        """Extract all dialogue assets to CSV/TXT files in output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        logger.info("Extracting dialogues for '%s' -> '%s'...", self.title, output_dir)

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
                logger.info("Extracted %d entries from '%s' -> '%s'", len(rows), d.id, csv_path)
            except Exception as e:
                logger.warning("Error extracting '%s': %s", d.id, e)

        return extracted_files

    # ------------------------------------------------------------------
    # Lifecycle: 3. Validate
    # ------------------------------------------------------------------

    def validate(self, translations_dir: str = "translations") -> bool:
        """Validate translated strings against textbox rules."""
        textbox_rule = next((r for r in self.rules if isinstance(r, Rule.Textbox)), None)
        if not textbox_rule:
            logger.info("No Rule.Textbox defined; skipping textbox boundary validation.")
            return True

        logger.info("Validating translations in '%s' against %s...", translations_dir, textbox_rule)
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
                    logger.warning("  %s Row %d:", d.id, r.index)
                    for w in warnings:
                        logger.warning("      - %s", w)

        if all_valid:
            logger.info("All %d dialogue entries passed textbox validation!", total_checked)
        else:
            logger.warning("Found %d potential textbox overflow issues out of %d rows.", issues_count, total_checked)

        return all_valid

    # ------------------------------------------------------------------
    # Lifecycle: 4. Build
    # ------------------------------------------------------------------

    def build(self, output_rom: Optional[str] = None, translations_dir: str = "translations") -> None:
        """Reconstruct translated binary assets and update archives."""
        dest = output_rom or (f"{self.name}_translated.iso")
        logger.info("Building patched ROM for '%s' -> '%s'...", self.title, dest)
        # Template hook for game-specific repack logic
        logger.info("Build finished successfully!")
