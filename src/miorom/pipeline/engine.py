import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from miorom.archive.container import ArchiveContainer
from miorom.compression import compress, decompress
from miorom.formats.csv_handler import CsvHandler
from miorom.patch import create_patch
from miorom.platforms.gb import fix_gb_checksum
from miorom.platforms.gba import fix_gba_checksum
from miorom.platforms.md import fix_md_checksum
from miorom.platforms.n64 import fix_n64_checksum
from miorom.platforms.snes import SNESRom
from miorom.platforms.wii import U8Archive


class PipelineContext:
    """Shared state dictionary passed across pipeline steps."""

    def __init__(self, initial_data: Optional[Dict[str, Any]] = None):
        self.data: Dict[str, Any] = initial_data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any):
        self.data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any):
        self.data[key] = value

    def format_string(self, template: str) -> str:
        """Resolve variables in string like '{working_dir}/file.bin'."""
        try:
            return template.format(**self.data)
        except KeyError:
            return template


class PipelineStep:
    """Base class for an automated pipeline execution step."""

    step_type: str = "base"

    def run(self, context: PipelineContext) -> bool:
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        return {"step_type": self.step_type}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineStep":
        raise NotImplementedError


class DecompressStep(PipelineStep):
    step_type = "decompress"

    def __init__(self, input_path: str, output_path: str, format_name: str = "auto"):
        self.input_path = input_path
        self.output_path = output_path
        self.format_name = format_name

    def run(self, context: PipelineContext) -> bool:
        src = context.format_string(self.input_path)
        dst = context.format_string(self.output_path)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with open(src, "rb") as f:
            data = f.read()
        decompressed = decompress(data)
        with open(dst, "wb") as f:
            f.write(decompressed)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "format_name": self.format_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecompressStep":
        return cls(
            input_path=data["input_path"],
            output_path=data["output_path"],
            format_name=data.get("format_name", "auto"),
        )


class CompressStep(PipelineStep):
    step_type = "compress"

    def __init__(self, input_path: str, output_path: str, format_name: str = "lz10"):
        self.input_path = input_path
        self.output_path = output_path
        self.format_name = format_name

    def run(self, context: PipelineContext) -> bool:
        src = context.format_string(self.input_path)
        dst = context.format_string(self.output_path)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        with open(src, "rb") as f:
            data = f.read()
        compressed = compress(data, fmt=self.format_name)
        with open(dst, "wb") as f:
            f.write(compressed)
        return True


    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "format_name": self.format_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompressStep":
        return cls(
            input_path=data["input_path"],
            output_path=data["output_path"],
            format_name=data.get("format_name", "lz10"),
        )


class ExtractArchiveStep(PipelineStep):
    step_type = "extract_archive"

    def __init__(self, archive_path: str, output_dir: str, archive_type: str = "u8"):
        self.archive_path = archive_path
        self.output_dir = output_dir
        self.archive_type = archive_type

    def run(self, context: PipelineContext) -> bool:
        src = context.format_string(self.archive_path)
        dst = context.format_string(self.output_dir)
        os.makedirs(dst, exist_ok=True)

        with open(src, "rb") as f:
            raw = f.read()

        if self.archive_type.lower() == "u8":
            u8 = U8Archive.from_bytes(raw)
            u8.extract_to_disk(dst)
        else:
            container = ArchiveContainer()
            with open(src, "rb") as stream:
                container.extract_to_dir(stream, dst)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "archive_path": self.archive_path,
            "output_dir": self.output_dir,
            "archive_type": self.archive_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractArchiveStep":
        return cls(
            archive_path=data["archive_path"],
            output_dir=data["output_dir"],
            archive_type=data.get("archive_type", "u8"),
        )


class PackArchiveStep(PipelineStep):
    step_type = "pack_archive"

    def __init__(self, input_dir: str, output_path: str, archive_type: str = "u8"):
        self.input_dir = input_dir
        self.output_path = output_path
        self.archive_type = archive_type

    def run(self, context: PipelineContext) -> bool:
        src = context.format_string(self.input_dir)
        dst = context.format_string(self.output_path)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)

        if self.archive_type.lower() == "u8":
            u8 = U8Archive.from_directory(src)
            packed = u8.to_bytes()
        else:
            container = ArchiveContainer()
            container.load_from_dir(src)
            packed = container.pack()

        with open(dst, "wb") as f:
            f.write(packed)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "input_dir": self.input_dir,
            "output_path": self.output_path,
            "archive_type": self.archive_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackArchiveStep":
        return cls(
            input_dir=data["input_dir"],
            output_path=data["output_path"],
            archive_type=data.get("archive_type", "u8"),
        )


class FixChecksumStep(PipelineStep):
    step_type = "fix_checksum"

    def __init__(self, rom_path: str, platform: str):
        self.rom_path = rom_path
        self.platform = platform.lower()

    def run(self, context: PipelineContext) -> bool:
        src = context.format_string(self.rom_path)
        with open(src, "rb") as f:
            data = f.read()

        if self.platform in ("n64", "z64", "v64"):
            fixed = fix_n64_checksum(data)
        elif self.platform in ("gba", "advance"):
            fixed = fix_gba_checksum(data)
        elif self.platform in ("gb", "gbc", "gameboy"):
            fixed = fix_gb_checksum(data)
        elif self.platform in ("md", "genesis", "megadrive"):
            fixed = fix_md_checksum(data)
        elif self.platform in ("snes", "sfc"):
            snes = SNESRom(data)
            snes.fix_checksum()
            fixed = snes.to_bytes()
        else:
            raise ValueError(f"Unsupported platform for checksum fix: {self.platform}")

        with open(src, "wb") as f:
            f.write(fixed)
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "rom_path": self.rom_path,
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixChecksumStep":
        return cls(
            rom_path=data["rom_path"],
            platform=data["platform"],
        )


class CreatePatchStep(PipelineStep):
    step_type = "create_patch"

    def __init__(self, original_path: str, modified_path: str, patch_output_path: str, patch_format: str = "bps"):
        self.original_path = original_path
        self.modified_path = modified_path
        self.patch_output_path = patch_output_path
        self.patch_format = patch_format

    def run(self, context: PipelineContext) -> bool:
        orig = context.format_string(self.original_path)
        mod = context.format_string(self.modified_path)
        out = context.format_string(self.patch_output_path)
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

        create_patch(orig, mod, out, fmt=self.patch_format)
        return True


    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "original_path": self.original_path,
            "modified_path": self.modified_path,
            "patch_output_path": self.patch_output_path,
            "patch_format": self.patch_format,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CreatePatchStep":
        return cls(
            original_path=data["original_path"],
            modified_path=data["modified_path"],
            patch_output_path=data["patch_output_path"],
            patch_format=data.get("patch_format", "bps"),
        )


STEP_REGISTRY: Dict[str, Type[PipelineStep]] = {
    DecompressStep.step_type: DecompressStep,
    CompressStep.step_type: CompressStep,
    ExtractArchiveStep.step_type: ExtractArchiveStep,
    PackArchiveStep.step_type: PackArchiveStep,
    FixChecksumStep.step_type: FixChecksumStep,
    CreatePatchStep.step_type: CreatePatchStep,
}


class PipelineRecipe:
    """
    Automated translation & repacking pipeline recipe.
    Executes an ordered sequence of declarative steps with parameter context substitution.
    """

    def __init__(self, name: str = "default_recipe", steps: Optional[List[PipelineStep]] = None):
        self.name = name
        self.steps: List[PipelineStep] = steps or []

    def add_step(self, step: PipelineStep) -> "PipelineRecipe":
        self.steps.append(step)
        return self

    def execute(self, initial_context: Optional[Dict[str, Any]] = None) -> PipelineContext:
        context = PipelineContext(initial_context)
        for idx, step in enumerate(self.steps):
            success = step.run(context)
            if not success:
                raise RuntimeError(f"Pipeline step #{idx + 1} ({step.step_type}) failed.")
        return context

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PipelineRecipe":
        name = data.get("name", "recipe")
        raw_steps = data.get("steps", [])
        steps = []
        for s in raw_steps:
            stype = s.get("step_type")
            step_cls = STEP_REGISTRY.get(stype)
            if step_cls:
                steps.append(step_cls.from_dict(s))
            else:
                raise ValueError(f"Unknown pipeline step type: '{stype}'")
        return cls(name=name, steps=steps)

    @classmethod
    def from_json(cls, json_str: str) -> "PipelineRecipe":
        return cls.from_dict(json.loads(json_str))

    def save_file(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def load_file(cls, filepath: str) -> "PipelineRecipe":
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())
