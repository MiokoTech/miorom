# Menambahkan Platform Baru

MioROM menggunakan pola **plugin registry** untuk mendukung platform ROM.
Fondasi sudah ada di `src/miorom/rom/base.py` (`BaseRomHandler` ABC) dan
`src/miorom/rom/manager.py` (`RomManager.register()`).

## Quickstart

```python
from miorom.rom.base import BaseRomHandler
from miorom.rom.manager import RomManager

class MyConsoleRomHandler(BaseRomHandler):
    """Handler untuk konsol fiktif 'MyConsole'."""
    name = "myconsole"

    @staticmethod
    def can_handle(data: bytes, filepath=None) -> bool:
        return len(data) >= 16 and data[:8] == b"MYCON001"

    def unpack(self, data: bytes, output_dir: str, filepath=None, **kw) -> dict:
        # Parse header, extract files, tulis ke output_dir
        # Return metadata dict (harus punya "platform" dan "format" keys)
        ...
        return {"platform": "MyConsole", "format": "myconsole", "file_count": N}

    def repack(self, input_dir: str, **kw) -> bytes:
        # Baca file dari output_dir, rebuild binary
        ...
        return b"..."

# Register
manager = RomManager()
manager.register(MyConsoleRomHandler)
```

## Structural Handler (Tanpa Inheritance)

Class lama dari sistem lain tetap bisa didaftarkan jika strukturnya cocok
 dengan `RomHandlerProtocol`:

```python
from miorom.rom.manager import RomManager
from miorom.rom.protocols import RomHandlerProtocol

class LegacyHandler:
    name = "legacy"

    def can_handle(self, data, filepath=None): ...
    def unpack(self, data, output_dir, **kwargs): ...
    def repack(self, input_dir, **kwargs): ...

if isinstance(LegacyHandler(), RomHandlerProtocol):
    RomManager().register(LegacyHandler())
```

## Rules

1. `can_handle(data, filepath)` harus **deterministik dan murah** — dipanggil
   di setiap `detect_format()` scan.
2. `unpack()` wajib menulis manifest `miorom.meta.json` di `output_dir`.
3. `repack()` harus bisa membaca ulang manifest untuk reconstruct.
4. Raise `ParseError` (dari `miorom.errors`) untuk bad magic / truncated data.
