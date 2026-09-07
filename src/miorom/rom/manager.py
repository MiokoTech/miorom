import os
import json
from typing import Dict, Any, Optional, List, Union

from miorom import __version__
from miorom.rom.base import BaseRomHandler
from miorom.rom.handlers import (
    NDSRomHandler,
    GameCubeRomHandler,
    U8RomHandler,
    NarcRomHandler,
    Iso9660RomHandler,
    CartridgeRomHandler,
)


class RomManager:
    """
    Central dispatcher and orchestration manager for ROM unpacking and repacking.
    Auto-detects container format from binary magic bytes or file signatures.
    """

    def __init__(self):
        self.handlers: Dict[str, BaseRomHandler] = {}
        self._register_default_handlers()

    def _register_default_handlers(self):
        self.register(NDSRomHandler())
        self.register(GameCubeRomHandler())
        self.register(U8RomHandler())
        self.register(NarcRomHandler())
        self.register(Iso9660RomHandler())
        self.register(CartridgeRomHandler())

    def register(self, handler: BaseRomHandler):
        """Registers a custom or platform-specific ROM handler."""
        self.handlers[handler.name] = handler

    def get_handler(self, fmt: str) -> BaseRomHandler:
        """Retrieves a handler by format name."""
        clean = fmt.lower().strip()
        if clean not in self.handlers:
            supported = ", ".join(sorted(self.handlers.keys()))
            raise ValueError(f"Unknown ROM format '{fmt}'. Supported formats: {supported}")
        return self.handlers[clean]

    def detect_format(self, data: bytes, filepath: Optional[str] = None) -> Optional[str]:
        """Auto-detects the container or ROM format from binary data or file path."""
        # Check handlers in precedence order (specific container before generic cartridge)
        order = ["nds", "gamecube", "u8", "narc", "iso9660", "cartridge"]
        for name in order:
            handler = self.handlers.get(name)
            if handler and handler.can_handle(data, filepath):
                return handler.name

        # Fallback to any other registered handler
        for name, handler in self.handlers.items():
            if name not in order and handler.can_handle(data, filepath):
                return name

        return None

    def unpack(
        self,
        source: Union[str, bytes],
        output_dir: str,
        fmt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Unpacks a ROM or archive into output_dir.
        Writes miorom.meta.json manifest containing structural metadata.
        """
        filepath: Optional[str] = None
        if isinstance(source, (str, os.PathLike)):
            filepath = str(source)
            with open(filepath, "rb") as f:
                data = f.read()
        else:
            data = source

        if not fmt:
            fmt = self.detect_format(data, filepath)
            if not fmt:
                raise ValueError(
                    f"Could not automatically detect ROM container format for '{filepath or 'bytes'}'. "
                    f"Please specify format explicitly (choices: {', '.join(sorted(self.handlers.keys()))})."
                )

        handler = self.get_handler(fmt)
        os.makedirs(output_dir, exist_ok=True)

        meta = handler.unpack(data, output_dir, filepath=filepath, **kwargs)
        meta["generator"] = "miorom"
        meta["version"] = __version__
        meta["format"] = handler.name

        # Write metadata manifest
        meta_path = os.path.join(output_dir, "miorom.meta.json")
        with open(meta_path, "w", encoding="utf-8") as f_meta:
            json.dump(meta, f_meta, indent=2)

        return meta

    def repack(
        self,
        input_dir: str,
        output_path: Optional[str] = None,
        fmt: Optional[str] = None,
        **kwargs
    ) -> bytes:
        """
        Repacks an unpacked directory back into a binary ROM or archive image.
        Optionally saves the resulting file to output_path.
        """
        if not os.path.isdir(input_dir):
            raise NotADirectoryError(f"Input directory does not exist: '{input_dir}'")

        # Infer format if not provided
        if not fmt:
            meta_path = os.path.join(input_dir, "miorom.meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f_meta:
                        meta = json.load(f_meta)
                    fmt = meta.get("format")
                except Exception:
                    pass

        if not fmt:
            # Check filesystem clues
            sys_dir = os.path.join(input_dir, "sys")
            if os.path.isfile(os.path.join(sys_dir, "arm9.bin")):
                fmt = "nds"
            elif os.path.isfile(os.path.join(sys_dir, "disc_base.bin")):
                fmt = "gamecube"
            elif os.path.isfile(os.path.join(sys_dir, "iso_base.bin")):
                fmt = "iso9660"
            elif os.path.isfile(os.path.join(input_dir, "rom.bin")):
                fmt = "cartridge"
            else:
                fmt = "u8"

        handler = self.get_handler(fmt)
        repacked_data = handler.repack(input_dir, **kwargs)

        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(output_path, "wb") as f_out:
                f_out.write(repacked_data)

        return repacked_data


# Default global instance
_default_manager = RomManager()


def unpack_rom(
    rom_path: str,
    output_dir: str,
    fmt: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    High-level convenience function to unpack a ROM or container to an output directory.
    """
    return _default_manager.unpack(rom_path, output_dir, fmt=fmt, **kwargs)


def repack_rom(
    unpacked_dir: str,
    output_path: str,
    fmt: Optional[str] = None,
    **kwargs
) -> bytes:
    """
    High-level convenience function to repack an unpacked directory back into a ROM image.
    """
    return _default_manager.repack(unpacked_dir, output_path=output_path, fmt=fmt, **kwargs)
