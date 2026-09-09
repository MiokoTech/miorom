# Adding New Platforms: Plugin & Extension Guide

MioROM is designed with an extensible, plugin-friendly architecture. Developers can add support for new console architectures, disc images, and cartridge containers without modifying or forking the core library.

---

## Extension Mechanisms

MioROM provides two parallel avenues for platform extensibility:
1. **Inheritance**: Subclass `miorom.rom.base.BaseRomHandler`.
2. **Structural Typing (Protocols)**: Implement `miorom.rom.protocols.RomHandlerProtocol` without inheriting from any MioROM class.

Both approaches work identically with `RomManager`.

---

## 1. Defining a Platform Handler

A platform handler defines three fundamental operations:
- `can_handle(data: bytes, filepath: Optional[str]) -> bool`: Inspects magic bytes or file extension.
- `unpack(data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]`: Decompresses and extracts files into `output_dir`.
- `repack(input_dir: str, **kwargs) -> bytes`: Compiles directory contents back into a valid ROM image and recalibrates hardware checksums.

### Example: Custom Console Handler

```python
import os
import struct
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.core.schema import BinaryStruct, FixedString, U32
from miorom.security import sanitize_extract_path


class WonderSwanHeader(BinaryStruct):
    _endian = "<"
    magic = FixedString(4, default="WS01")
    rom_size = U32()


class WonderSwanRomHandler(BaseRomHandler):
    name = "wonderswan"
    description = "Bandai WonderSwan / Color ROM Image"
    extensions = [".ws", ".wsc"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions:
                return True
        if len(data) >= 0x10 and data.startswith(b"WS01"):
            return True
        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        os.makedirs(output_dir, exist_ok=True)

        # 1. Parse header
        hdr = WonderSwanHeader.from_bytes(data)

        # 2. Extract system header
        sys_dir = os.path.join(output_dir, "sys")
        os.makedirs(sys_dir, exist_ok=True)
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(data[:0x10])

        # 3. Extract ROM payload
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(root_dir, exist_ok=True)
        with open(os.path.join(root_dir, "rom.bin"), "wb") as f:
            f.write(data[0x10:])

        return {
            "format": self.name,
            "platform": "Bandai WonderSwan",
            "rom_size": len(data),
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        sys_dir = os.path.join(input_dir, "sys")
        root_dir = os.path.join(input_dir, "root")

        with open(os.path.join(sys_dir, "header.bin"), "rb") as f:
            hdr_bytes = f.read()
        with open(os.path.join(root_dir, "rom.bin"), "rb") as f:
            payload = f.read()

        return hdr_bytes + payload
```

---

## 2. In-Code Registration

Register your handler dynamically at runtime with `RomManager`:

```python
from miorom.rom.manager import RomManager

# Instantiate manager
manager = RomManager()

# Register custom handler
manager.register(WonderSwanRomHandler())

# Now unpack and repack will auto-detect your platform!
meta = manager.unpack("game.wsc", "unpacked_ws/")
manager.repack("unpacked_ws/", output_path="game_patched.wsc")
```

---

## 3. Automatic Discovery via `entry_points`

To publish a standalone package (e.g. `pip install miorom-wonderswan`), expose your handler in your package's `pyproject.toml` under the `miorom.platforms` entry-point group:

```toml
[project.entry-points."miorom.platforms"]
wonderswan = "miorom_wonderswan.handler:WonderSwanRomHandler"
```

When users install your package, `miorom`'s default `RomManager` will automatically discover and register your handler on startup via `importlib.metadata.entry_points`. Users can immediately use `miorom unpack game.wsc out/` via CLI without writing any code.

---

## 4. Custom Compression Codecs

Custom compression algorithms can also be registered into MioROM's central codec registry:

```python
from miorom.registry import register_codec


class CustomLzCodec:
    @staticmethod
    def decompress(data: bytes) -> bytes:
        ...

    @staticmethod
    def compress(data: bytes) -> bytes:
        ...


# Register by unique algorithm identifier
register_codec("custom_lz", CustomLzCodec)
```
