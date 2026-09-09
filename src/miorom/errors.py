"""
miorom.exceptions
~~~~~~~~~~~~~~~~~
Unified exception hierarchy for the MioROM library.

All errors raised intentionally by MioROM derive from :class:`MioromError`,
so library consumers can distinguish "the binary/format is at fault" from
"my code is at fault" with a single except clause:

    try:
        meta = unpack_rom("game.nds", "out/")
    except MioromError:
        ...
"""

from typing import Optional

from typing import Optional

__all__ = [
    "MioromError",
    "ParseError",
    "UnsupportedFormatError",
    "ChecksumError",
    "RelocationError",
    "PointerOverflowError",
    "CompressionError",
    "PatchError",
    "SymbolError",
]


class MioromError(Exception):
    """Base class for all errors raised intentionally by MioROM."""

    def __init__(
        self,
        message: object = "",
        *,
        offset: Optional[int] = None,
        expected: object = None,
        actual: object = None,
        context: Optional[dict] = None,
    ) -> None:
        self.message = str(message)
        self.offset = offset
        self.expected = expected
        self.actual = actual
        self.context = dict(context or {})
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        details = []
        if self.offset is not None:
            details.append(f"offset=0x{self.offset:X}")
        if self.expected is not None or self.actual is not None:
            details.append(f"expected={self.expected!r}")
            details.append(f"actual={self.actual!r}")
        if self.context:
            details.append(f"context={self.context!r}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{type(self).__name__}({self.message!r}{suffix})"


class ParseError(MioromError, ValueError):
    """A binary structure could not be parsed (bad magic, truncated data, ...)."""


class UnsupportedFormatError(MioromError, ValueError):
    """The input is recognized as out-of-scope or the format is unknown."""


class ChecksumError(MioromError):
    """A hardware checksum (CIC, CRC, complement) verification or repair failed."""


class RelocationError(MioromError, ValueError):
    """A pointer or data block could not be relocated safely."""


class PointerOverflowError(RelocationError):
    """A relative pointer exceeds the signed range of its backing integer field."""


class CompressionError(MioromError, ValueError):
    """Compressed data is corrupt, or decompression output is malformed."""


class PatchError(MioromError, ValueError):
    """A patch could not be applied, built, or serialized."""


class SymbolError(MioromError):
    """A symbol map entry is malformed or a required symbol is missing."""
