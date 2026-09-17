"""
src/miorom/platforms/wii/riivolution.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii Riivolution XML Mod Engine.
Provides declarative parser, builder, automated delta packager, and virtual disc patcher
for Riivolution XML mods (.xml) compatible with retail Wii hardware and Dolphin Emulator.

Zero external dependencies: uses Python stdlib xml.etree.ElementTree and hashlib.
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Union

from miorom.errors import ParseError, PatchError
from miorom.result import MioRomResult

if TYPE_CHECKING:
    from miorom.platforms.wii.disc import WiiDisc


@dataclass
class FileRedirect:
    """A single file redirect rule from virtual disc path to external file path."""

    disc_path: str
    external_path: str
    create: bool = True
    offset: int = 0
    resize: bool = True

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("file")
        elem.set("disc", self.disc_path)
        elem.set("external", self.external_path)
        if not self.create:
            elem.set("create", "false")
        if self.offset != 0:
            elem.set("offset", hex(self.offset))
        if not self.resize:
            elem.set("resize", "false")
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> FileRedirect:
        disc = elem.get("disc", "")
        external = elem.get("external", "")
        if not disc or not external:
            raise ParseError("Riivolution <file> element must contain both 'disc' and 'external' attributes.")

        create_str = elem.get("create", "true").lower()
        create = create_str not in ("false", "0")

        offset_str = elem.get("offset", "0")
        try:
            offset = int(offset_str, 0)
        except ValueError:
            offset = 0

        resize_str = elem.get("resize", "true").lower()
        resize = resize_str not in ("false", "0")

        return cls(
            disc_path=disc,
            external_path=external,
            create=create,
            offset=offset,
            resize=resize,
        )


@dataclass
class FolderRedirect:
    """A directory redirect rule mapping virtual disc directory to external folder."""

    disc_path: str
    external_path: str
    recursive: bool = True
    create: bool = True

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("folder")
        elem.set("disc", self.disc_path)
        elem.set("external", self.external_path)
        if not self.recursive:
            elem.set("recursive", "false")
        if not self.create:
            elem.set("create", "false")
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> FolderRedirect:
        disc = elem.get("disc", "")
        external = elem.get("external", "")
        if not disc or not external:
            raise ParseError("Riivolution <folder> element must contain both 'disc' and 'external' attributes.")

        recursive_str = elem.get("recursive", "true").lower()
        recursive = recursive_str not in ("false", "0")

        create_str = elem.get("create", "true").lower()
        create = create_str not in ("false", "0")

        return cls(
            disc_path=disc,
            external_path=external,
            recursive=recursive,
            create=create,
        )


@dataclass
class MemoryPatch:
    """A memory patch rule writing bytes to virtual RAM / DOL address."""

    offset: int
    value: bytes
    original: Optional[bytes] = None

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("memory")
        elem.set("offset", hex(self.offset))
        elem.set("value", self.value.hex())
        if self.original is not None:
            elem.set("original", self.original.hex())
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> MemoryPatch:
        offset_str = elem.get("offset", "")
        value_str = elem.get("value", "")
        if not offset_str or not value_str:
            raise ParseError("Riivolution <memory> element must have 'offset' and 'value'.")

        offset = int(offset_str, 0)
        value = bytes.fromhex(value_str.replace(" ", ""))

        orig_str = elem.get("original")
        original = bytes.fromhex(orig_str.replace(" ", "")) if orig_str else None

        return cls(offset=offset, value=value, original=original)


@dataclass
class RiivolutionPatch:
    """A collection of file, folder, and memory patch rules associated with a patch ID."""

    id: str
    files: List[FileRedirect] = field(default_factory=list)
    folders: List[FolderRedirect] = field(default_factory=list)
    memory: List[MemoryPatch] = field(default_factory=list)

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("patch")
        elem.set("id", self.id)
        for f_redirect in self.files:
            elem.append(f_redirect.to_xml_element())
        for f_folder in self.folders:
            elem.append(f_folder.to_xml_element())
        for mem in self.memory:
            elem.append(mem.to_xml_element())
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> RiivolutionPatch:
        patch_id = elem.get("id", "")
        if not patch_id:
            raise ParseError("Riivolution <patch> element must have an 'id' attribute.")

        patch = cls(id=patch_id)
        for child in elem:
            tag = child.tag.lower()
            if tag == "file":
                patch.files.append(FileRedirect.from_xml_element(child))
            elif tag == "folder":
                patch.folders.append(FolderRedirect.from_xml_element(child))
            elif tag == "memory":
                patch.memory.append(MemoryPatch.from_xml_element(child))
        return patch


@dataclass
class RiivolutionChoice:
    """An option choice referencing one or more patch IDs."""

    name: str
    patch_ids: List[str] = field(default_factory=list)

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("choice")
        elem.set("name", self.name)
        for pid in self.patch_ids:
            patch_ref = ET.SubElement(elem, "patch")
            patch_ref.set("id", pid)
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> RiivolutionChoice:
        name = elem.get("name", "")
        choice = cls(name=name)
        for child in elem:
            if child.tag.lower() == "patch" and child.get("id"):
                choice.patch_ids.append(child.get("id"))  # type: ignore[arg-type]
        return choice


@dataclass
class RiivolutionOption:
    """A selectable option containing multiple choices."""

    name: str
    id: str = ""
    default_choice: int = 0
    choices: List[RiivolutionChoice] = field(default_factory=list)

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("option")
        elem.set("name", self.name)
        if self.id:
            elem.set("id", self.id)
        if self.default_choice != 0:
            elem.set("default", str(self.default_choice))
        for choice in self.choices:
            elem.append(choice.to_xml_element())
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> RiivolutionOption:
        name = elem.get("name", "")
        opt_id = elem.get("id", "")
        try:
            default_choice = int(elem.get("default", "0"))
        except ValueError:
            default_choice = 0

        opt = cls(name=name, id=opt_id, default_choice=default_choice)
        for child in elem:
            if child.tag.lower() == "choice":
                opt.choices.append(RiivolutionChoice.from_xml_element(child))
        return opt


@dataclass
class RiivolutionSection:
    """A grouping section for options."""

    name: str
    options: List[RiivolutionOption] = field(default_factory=list)

    def to_xml_element(self) -> ET.Element:
        elem = ET.Element("section")
        elem.set("name", self.name)
        for opt in self.options:
            elem.append(opt.to_xml_element())
        return elem

    @classmethod
    def from_xml_element(cls, elem: ET.Element) -> RiivolutionSection:
        name = elem.get("name", "")
        sec = cls(name=name)
        for child in elem:
            if child.tag.lower() == "option":
                sec.options.append(RiivolutionOption.from_xml_element(child))
        return sec


class RiivolutionFile:
    """
    Representation of a complete Riivolution XML mod definition document (<wiidisc>).
    Provides bidirectional parsing, serialization, and patch resolution.
    """

    def __init__(
        self,
        version: int = 1,
        game_ids: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        sections: Optional[List[RiivolutionSection]] = None,
        patches: Optional[Dict[str, RiivolutionPatch]] = None,
    ) -> None:
        self.version = version
        self.game_ids = list(game_ids) if game_ids else []
        self.regions = list(regions) if regions else []
        self.sections = list(sections) if sections else []
        self.patches: Dict[str, RiivolutionPatch] = dict(patches) if patches else {}

    def add_patch(self, patch: RiivolutionPatch) -> None:
        """Register a patch definition in this document."""
        self.patches[patch.id] = patch

    def get_patch(self, patch_id: str) -> Optional[RiivolutionPatch]:
        """Retrieve a registered patch by ID."""
        return self.patches.get(patch_id)

    def get_active_patches(
        self, selected_choices: Optional[Dict[str, int]] = None
    ) -> List[RiivolutionPatch]:
        """
        Resolves which patches are active based on user selected choices.
        If selected_choices is omitted, uses the default choice for each option.
        If no options are defined, returns all registered patches.
        """
        if not self.sections:
            return list(self.patches.values())

        active_patch_ids: set[str] = set()
        choices_map = selected_choices or {}

        for section in self.sections:
            for option in section.options:
                if not option.choices:
                    continue

                # Look up selected index (or fallback to option.default_choice)
                choice_idx = choices_map.get(option.id, choices_map.get(option.name, option.default_choice))
                if 0 <= choice_idx < len(option.choices):
                    choice = option.choices[choice_idx]
                    for pid in choice.patch_ids:
                        active_patch_ids.add(pid)

        return [self.patches[pid] for pid in active_patch_ids if pid in self.patches]

    def matches_game_id(self, game_id: str) -> bool:
        """Checks whether this XML targets or matches the given disc Game ID."""
        if not self.game_ids:
            return True
        game_id_clean = game_id.strip()
        for gid in self.game_ids:
            gid_clean = gid.strip()
            if game_id_clean.startswith(gid_clean) or gid_clean.startswith(game_id_clean):
                return True
        return False

    @classmethod
    def from_xml(cls, source: Union[str, bytes, Path]) -> RiivolutionFile:
        """Parse Riivolution XML from a string, bytes, or file path."""
        if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source and os.path.exists(source)):
            tree = ET.parse(str(source))
            root = tree.getroot()
        elif isinstance(source, (str, bytes)):
            text = source if isinstance(source, str) else source.decode("utf-8")
            root = ET.fromstring(text)
        else:
            raise ParseError(f"Unsupported XML source type: {type(source)}")

        if root.tag.lower() != "wiidisc":
            raise ParseError(f"Invalid Riivolution root tag: expected 'wiidisc', got '{root.tag}'")

        try:
            version = int(root.get("version", "1"))
        except ValueError:
            version = 1

        game_ids: List[str] = []
        regions: List[str] = []
        sections: List[RiivolutionSection] = []
        patches: Dict[str, RiivolutionPatch] = {}

        for child in root:
            tag = child.tag.lower()
            if tag == "id":
                gid = child.get("game")
                if gid:
                    game_ids.append(gid)
            elif tag == "region":
                reg = child.get("type")
                if reg:
                    regions.append(reg)
            elif tag == "options":
                for sec_elem in child:
                    if sec_elem.tag.lower() == "section":
                        sections.append(RiivolutionSection.from_xml_element(sec_elem))
            elif tag == "patch":
                patch = RiivolutionPatch.from_xml_element(child)
                patches[patch.id] = patch

        return cls(
            version=version,
            game_ids=game_ids,
            regions=regions,
            sections=sections,
            patches=patches,
        )

    def to_xml(self, pretty: bool = True) -> str:
        """Serializes document to XML string."""
        root = ET.Element("wiidisc")
        root.set("version", str(self.version))

        for gid in self.game_ids:
            id_elem = ET.SubElement(root, "id")
            id_elem.set("game", gid)

        for reg in self.regions:
            reg_elem = ET.SubElement(root, "region")
            reg_elem.set("type", reg)

        if self.sections:
            options_elem = ET.SubElement(root, "options")
            for sec in self.sections:
                options_elem.append(sec.to_xml_element())

        for patch in self.patches.values():
            root.append(patch.to_xml_element())

        if pretty and hasattr(ET, "indent"):
            ET.indent(root, space="  ")

        xml_str = ET.tostring(root, encoding="utf-8", method="xml").decode("utf-8")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + xml_str

    def save(self, path: Union[str, Path]) -> None:
        """Save XML document to file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(self.to_xml(pretty=True))


@dataclass
class RiivolutionPackageSummary(MioRomResult):
    """Summary report of Riivolution package generation."""

    mod_name: str
    game_id: str
    xml_path: Path
    payload_dir: Path
    modified_files_count: int
    added_files_count: int
    total_payload_bytes: int
    modified_file_paths: List[str]


def _compute_file_sha256(filepath: Path) -> str:
    """Computes SHA-256 hash in streaming 64 KB chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def create_riivolution_package(
    original_root: Union[str, Path],
    modified_root: Union[str, Path],
    output_dir: Union[str, Path],
    mod_name: str,
    game_ids: Union[str, Sequence[str]],
    section_name: str = "Translation",
    option_name: str = "Language Mod",
    choice_name: str = "Enabled",
    external_prefix: Optional[str] = None,
) -> RiivolutionPackageSummary:
    """
    Compares original game assets directory with modified project directory,
    identifies modified and newly added files, and copies delta assets into
    a standard Riivolution SD Card / Dolphin layout:
        {output_dir}/riivolution/{mod_name}.xml
        {output_dir}/{mod_name}/... (delta assets only)

    Returns RiivolutionPackageSummary.
    """
    orig_path = Path(original_root).resolve()
    mod_path = Path(modified_root).resolve()
    out_path = Path(output_dir).resolve()

    if not orig_path.is_dir():
        raise PatchError(f"Original root directory not found: {orig_path}")
    if not mod_path.is_dir():
        raise PatchError(f"Modified root directory not found: {mod_path}")

    prefix = external_prefix.strip("/") if external_prefix else mod_name
    xml_dir = out_path / "riivolution"
    payload_dir = out_path / prefix
    xml_dir.mkdir(parents=True, exist_ok=True)
    payload_dir.mkdir(parents=True, exist_ok=True)

    gids = [game_ids] if isinstance(game_ids, str) else list(game_ids)
    primary_gid = gids[0] if gids else "WII_GAME"

    modified_count = 0
    added_count = 0
    total_bytes = 0
    modified_paths: List[str] = []
    file_redirects: List[FileRedirect] = []

    # Traverse all files in modified_root
    for root_dir, _, filenames in os.walk(mod_path):
        for filename in filenames:
            mod_file = Path(root_dir) / filename
            rel_path = mod_file.relative_to(mod_path)
            rel_path_str = str(rel_path).replace("\\", "/")

            # Normalize virtual disc path (strip leading 'root/' or 'files/')
            disc_rel_path = rel_path_str
            if disc_rel_path.startswith("root/"):
                disc_rel_path = disc_rel_path[5:]
            elif disc_rel_path.startswith("files/"):
                disc_rel_path = disc_rel_path[6:]

            orig_file = orig_path / rel_path
            # Check fallbacks if original or modified was unpacked with/without root/ or files/
            if not orig_file.exists():
                for candidate in (
                    orig_path / disc_rel_path,
                    orig_path / "files" / disc_rel_path,
                    orig_path / "root" / disc_rel_path,
                ):
                    if candidate.exists():
                        orig_file = candidate
                        break

            is_modified = False
            is_added = False

            if not orig_file.exists():
                is_added = True
            else:
                mod_size = mod_file.stat().st_size
                orig_size = orig_file.stat().st_size
                if mod_size != orig_size:
                    is_modified = True
                else:
                    if _compute_file_sha256(mod_file) != _compute_file_sha256(orig_file):
                        is_modified = True

            if is_modified or is_added:
                if is_added:
                    added_count += 1
                else:
                    modified_count += 1

                file_size = mod_file.stat().st_size
                total_bytes += file_size
                modified_paths.append(rel_path_str)

                # Destination path in mod package
                dest_file = payload_dir / disc_rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                with open(mod_file, "rb") as src_f, open(dest_file, "wb") as dst_f:
                    dst_f.write(src_f.read())

                # Virtual disc path in XML starts with '/'
                virtual_disc_path = "/" + disc_rel_path.lstrip("/")
                external_file_path = f"/{prefix}/" + disc_rel_path.lstrip("/")

                file_redirects.append(
                    FileRedirect(
                        disc_path=virtual_disc_path,
                        external_path=external_file_path,
                        create=True,
                    )
                )

    # Generate XML document
    patch_id = f"patch_{mod_name.lower()}"
    patch = RiivolutionPatch(id=patch_id, files=file_redirects)

    choice_on = RiivolutionChoice(name=choice_name, patch_ids=[patch_id])
    choice_off = RiivolutionChoice(name="Disabled", patch_ids=[])

    option = RiivolutionOption(
        name=option_name,
        id=f"opt_{mod_name.lower()}",
        default_choice=1,
        choices=[choice_off, choice_on],
    )

    section = RiivolutionSection(name=section_name, options=[option])

    xml_file = RiivolutionFile(
        version=1,
        game_ids=gids,
        sections=[section],
        patches={patch_id: patch},
    )

    xml_output_path = xml_dir / f"{mod_name}.xml"
    xml_file.save(xml_output_path)

    return RiivolutionPackageSummary(
        mod_name=mod_name,
        game_id=primary_gid,
        xml_path=xml_output_path,
        payload_dir=payload_dir,
        modified_files_count=modified_count,
        added_files_count=added_count,
        total_payload_bytes=total_bytes,
        modified_file_paths=modified_paths,
    )


def apply_riivolution_to_disc(
    disc: WiiDisc,
    riivolution_file: RiivolutionFile,
    external_root_dir: Union[str, Path],
    selected_choices: Optional[Dict[str, int]] = None,
    partition_index: int = 0,
    apply_memory_to_dol: bool = True,
) -> WiiDisc:
    """
    Applies active Riivolution patch rules (file redirects, folder redirects, memory patches)
    directly onto a WiiDisc instance in-memory.

    The returned disc can be saved to .iso, .wbfs, or .rvz directly.
    """
    ext_root = Path(external_root_dir).resolve()
    if not ext_root.is_dir():
        raise PatchError(f"External root directory does not exist: {ext_root}")

    # Verify Game ID
    game_id = disc.header.game_id
    if not riivolution_file.matches_game_id(game_id):
        raise PatchError(
            f"Riivolution mod targets {riivolution_file.game_ids} but disc Game ID is {game_id!r}."
        )

    if partition_index >= len(disc.partitions):
        raise PatchError(
            f"Partition index {partition_index} out of range (disc has {len(disc.partitions)} partitions)."
        )

    partition = disc.partitions[partition_index]
    active_patches = riivolution_file.get_active_patches(selected_choices)

    for patch in active_patches:
        # 1. Apply file redirects
        for f_redirect in patch.files:
            rel_ext = f_redirect.external_path.lstrip("/").replace("\\", "/")
            src_file = ext_root / rel_ext
            if not src_file.is_file():
                continue

            with open(src_file, "rb") as f:
                new_data = f.read()

            # Normalize virtual disc path to partition FST convention
            clean_disc_path = f_redirect.disc_path.lstrip("/")
            if clean_disc_path.lower() in ("main.dol", "sys/main.dol"):
                norm_disc_path = "sys/main.dol"
            elif clean_disc_path.lower().startswith("sys/"):
                norm_disc_path = clean_disc_path
            elif not clean_disc_path.startswith("files/"):
                norm_disc_path = "files/" + clean_disc_path
            else:
                norm_disc_path = clean_disc_path

            # If create is False, do not create non-existent files on disc
            if not f_redirect.create and norm_disc_path not in partition:
                continue

            if f_redirect.offset == 0:
                if not f_redirect.resize and norm_disc_path in partition:
                    orig_len = len(partition[norm_disc_path])
                    if len(new_data) > orig_len:
                        new_data = new_data[:orig_len]
                    elif len(new_data) < orig_len:
                        new_data = new_data + b"\x00" * (orig_len - len(new_data))
                partition[norm_disc_path] = new_data
            else:
                # Surgical sub-region replacement
                existing = partition.get(norm_disc_path, b"") or b""
                merged = bytearray(existing)
                needed_len = f_redirect.offset + len(new_data)
                if len(merged) < needed_len:
                    merged.extend(b"\x00" * (needed_len - len(merged)))
                merged[f_redirect.offset : f_redirect.offset + len(new_data)] = new_data
                if not f_redirect.resize and existing:
                    orig_len = len(existing)
                    if len(merged) > orig_len:
                        merged = merged[:orig_len]
                    elif len(merged) < orig_len:
                        merged.extend(b"\x00" * (orig_len - len(merged)))
                partition[norm_disc_path] = bytes(merged)

        # 2. Apply folder redirects
        for f_folder in patch.folders:
            rel_ext_folder = f_folder.external_path.lstrip("/").replace("\\", "/")
            src_folder = ext_root / rel_ext_folder
            if not src_folder.is_dir():
                continue

            disc_base = f_folder.disc_path.lstrip("/")
            if disc_base.lower().startswith("sys/"):
                pass
            elif not disc_base.startswith("files/"):
                disc_base = f"files/{disc_base}" if disc_base else "files"

            for root_dir, dirnames, filenames in os.walk(src_folder):
                if not f_folder.recursive:
                    dirnames.clear()
                for fname in filenames:
                    f_path = Path(root_dir) / fname
                    sub_rel = f_path.relative_to(src_folder)
                    sub_rel_str = str(sub_rel).replace("\\", "/")
                    target_fst_path = f"{disc_base.rstrip('/')}/{sub_rel_str.lstrip('/')}"
                    if not f_folder.create and target_fst_path not in partition:
                        continue
                    with open(f_path, "rb") as f:
                        partition[target_fst_path] = f.read()

        # 3. Apply memory patches to main.dol if requested
        if apply_memory_to_dol and patch.memory and partition.main_dol:
            from miorom.platforms.gc.dol import DolFile

            try:
                dol = DolFile.from_bytes(partition.main_dol)
            except Exception:
                dol = None

            if dol is not None:
                dol_modified = False
                for mem in patch.memory:
                    try:
                        if mem.original is not None:
                            curr_val = dol.read_memory(mem.offset, len(mem.original))
                            if curr_val != mem.original:
                                continue
                        dol.write_memory(mem.offset, mem.value)
                        dol_modified = True
                    except Exception:
                        # Memory address might be outside DOL virtual segments (e.g. heap/stack)
                        pass
                if dol_modified:
                    dol_bytes = dol.to_bytes()
                    partition.main_dol = dol_bytes
                    if "sys/main.dol" in partition.files:
                        partition.files["sys/main.dol"] = dol_bytes

    return disc
