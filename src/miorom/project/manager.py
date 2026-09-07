"""
miorom.project.manager
~~~~~~~~~~~~~~~~~~~~~~
Unified End-to-End ROM Bongkar-Pasang Project Workflow Engine.
Provides high-level workspace project initialization, text dumping to standard
translation catalogs (.po / .json), and one-command rebuilding with automated
text lengthening, VWF auto-pagination, heap relocation, and checksum verification.
"""

from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, List, Optional, Union

from miorom.core.integrity import RomIntegrityManager
from miorom.patch.relocator import RelocationSummary
from miorom.text.paginator import SmartAutoPaginator, PaginationConfig
from miorom.text.pipeline import StringTablePipeline
from miorom.text.po_handler import PoHandler


@dataclass
class ProjectManifest:
    """Project metadata and configuration for ROM translation workspace."""
    name: str
    platform: str
    text_tables: List[Dict[str, Any]] = field(default_factory=list)
    auto_paginate: bool = False
    pagination_config: Optional[Dict[str, Any]] = None
    auto_fix_integrity: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectManifest":
        return cls(
            name=data.get("name", "MioROM_Project"),
            platform=data.get("platform", "generic"),
            text_tables=data.get("text_tables", []),
            auto_paginate=data.get("auto_paginate", False),
            pagination_config=data.get("pagination_config"),
            auto_fix_integrity=data.get("auto_fix_integrity", True),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "platform": self.platform,
            "text_tables": self.text_tables,
            "auto_paginate": self.auto_paginate,
            "pagination_config": self.pagination_config,
            "auto_fix_integrity": self.auto_fix_integrity,
        }


@dataclass
class BuildResult:
    """Detailed summary of a ROM repack build."""
    project_name: str
    tables_injected: int
    total_strings: int
    total_overflowed: int
    checksum_repaired: bool
    output_size: int


class ProjectWorkflowManager:
    """
    Manages the full lifecycle of a translation project:
    Dump (Bongkar) -> Translate / Lengthen -> Build (Pasang).
    """

    @classmethod
    def init_project(
        cls,
        project_dir: str,
        name: str,
        platform: str = "generic",
        text_tables: Optional[List[Dict[str, Any]]] = None,
    ) -> ProjectManifest:
        """Initializes workspace directory structure and project.json."""
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, "texts"), exist_ok=True)
        os.makedirs(os.path.join(project_dir, "scripts"), exist_ok=True)

        manifest = ProjectManifest(
            name=name,
            platform=platform,
            text_tables=text_tables or [],
        )

        manifest_path = os.path.join(project_dir, "project.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2)

        return manifest

    @classmethod
    def dump_project(
        cls,
        rom_data: bytes,
        project_dir: str,
        manifest: ProjectManifest,
    ) -> List[str]:
        """
        Dumps all configured text tables in the ROM to editable GNU gettext .po files.
        Returns list of created PO file paths.
        """
        os.makedirs(os.path.join(project_dir, "texts"), exist_ok=True)
        created_files: List[str] = []

        for idx, tbl in enumerate(manifest.text_tables):
            name = tbl.get("name", f"table_{idx:02d}")
            po_filename = f"{name}.po"
            po_path = os.path.join(project_dir, "texts", po_filename)

            table_off = tbl["table_offset"]
            entry_count = tbl["entry_count"]
            ptr_size = tbl.get("pointer_size", 4)
            endian = tbl.get("endian", "<")
            base_addr = tbl.get("base_address", 0)

            StringTablePipeline.dump_to_po(
                buffer=rom_data,
                table_offset=table_off,
                entry_count=entry_count,
                output_path=po_path,
                pointer_size=ptr_size,
                endian=endian,
                base_address=base_addr,
            )
            created_files.append(po_path)

        return created_files

    @classmethod
    def build_project(
        cls,
        rom_buffer: bytearray,
        project_dir: str,
        output_rom_path: Optional[str] = None,
    ) -> BuildResult:
        """
        Repacks the translated project back into the ROM buffer:
        - Injects translated text (automatically expanding and relocating).
        - Applies auto-pagination if configured.
        - Auto-fixes ROM header checksum.
        - Writes output ROM if output_rom_path is specified.
        """
        manifest_path = os.path.join(project_dir, "project.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = ProjectManifest.from_dict(json.load(f))

        total_strings = 0
        total_overflowed = 0
        tables_injected = 0

        # Optional paginator
        paginator = None
        if manifest.auto_paginate:
            cfg = PaginationConfig()
            if manifest.pagination_config:
                cfg.max_width_px = manifest.pagination_config.get("max_width_px", cfg.max_width_px)
                cfg.max_lines_per_page = manifest.pagination_config.get("max_lines_per_page", cfg.max_lines_per_page)
                cfg.page_break_tag = manifest.pagination_config.get("page_break_tag", cfg.page_break_tag)
            paginator = SmartAutoPaginator(cfg)

        for idx, tbl in enumerate(manifest.text_tables):
            name = tbl.get("name", f"table_{idx:02d}")
            po_filename = f"{name}.po"
            po_path = os.path.join(project_dir, "texts", po_filename)

            if not os.path.exists(po_path):
                continue

            po_handler = PoHandler.from_file(po_path)

            if paginator:
                paginator.paginate_po(po_handler, in_place=True)

            table_off = tbl["table_offset"]
            ptr_size = tbl.get("pointer_size", 4)
            endian = tbl.get("endian", "<")
            base_addr = tbl.get("base_address", 0)

            summary = StringTablePipeline.inject_from_po(
                buffer=rom_buffer,
                po_source=po_handler,
                table_offset=table_off,
                pointer_size=ptr_size,
                endian=endian,
                base_address=base_addr,
                auto_relocate=True,
                auto_fix_integrity=False,  # Run once globally at the end
            )

            total_strings += summary.total_items
            total_overflowed += summary.total_overflowed
            tables_injected += 1

        repaired_checksum = False
        if manifest.auto_fix_integrity:
            fixed_data, report = RomIntegrityManager.fix(bytes(rom_buffer), platform=manifest.platform)
            rom_buffer[:len(fixed_data)] = fixed_data
            repaired_checksum = report.repaired

        if output_rom_path:
            with open(output_rom_path, "wb") as f:
                f.write(rom_buffer)

        return BuildResult(
            project_name=manifest.name,
            tables_injected=tables_injected,
            total_strings=total_strings,
            total_overflowed=total_overflowed,
            checksum_repaired=repaired_checksum,
            output_size=len(rom_buffer),
        )
