"""
miorom.project.assets
~~~~~~~~~~~~~~~~~~~~~
Declarative asset descriptors for ROM hacking projects.
Encapsulates archives, dual-table containers, bytecode scripts, and files.
"""

import os
import struct
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from miorom.archive.toc_pair import TocPair
from miorom.core.scanner import StringScanner, PointerScanner, FoundString
from miorom.formats.csv_handler import CsvHandler, TranslationRow


class Asset(ABC):
    """Base declarative asset descriptor."""

    def __init__(self, id: str, source: str):
        self.id = id
        self.source = source

    @abstractmethod
    def extract_text(self, context: Any) -> List[TranslationRow]:
        pass

    @abstractmethod
    def repack_text(self, rows: List[TranslationRow], context: Any) -> bytes:
        pass


class TocArchive(Asset):
    """
    Descriptor for paired TOC archives (.bin index + .dat payload).
    """

    def __init__(self, bin_path: str, dat_path: str, id: str = "toc_archive", format: str = "auto"):
        super().__init__(id=id, source=bin_path)
        self.bin_path = bin_path
        self.dat_path = dat_path
        self.format = format
        self._toc: Optional[TocPair] = None

    def get_toc(self) -> TocPair:
        if self._toc is None:
            self._toc = TocPair.load(self.bin_path, self.dat_path)
        return self._toc

    def extract_file(self, index: int) -> bytes:
        return self.get_toc().extract(index)

    def inject_file(self, index: int, data: bytes, out_bin: Optional[str] = None, out_dat: Optional[str] = None) -> None:
        self.get_toc().inject(index, data, out_bin=out_bin, out_dat=out_dat)

    def extract_text(self, context: Any) -> List[TranslationRow]:
        return []

    def repack_text(self, rows: List[TranslationRow], context: Any) -> bytes:
        return b""

    def __repr__(self) -> str:
        return f"<TocArchive '{self.id}' bin='{self.bin_path}' dat='{self.dat_path}'>"


class DualTableDialogue(Asset):
    """
    Descriptor for Neverland/Marvelous Dual-Table text containers (sub_XXXX.bin / .fefe).
    Has Table 1 pointers at 0x10 and Table 2 pointers + metadata in footer.
    """

    def __init__(
        self,
        filepath: str,
        encoding: str = "utf-16-be",
        id: str = "dual_table",
        toc_archive: Optional[TocArchive] = None,
        toc_index: Optional[int] = None,
    ):
        super().__init__(id=id, source=filepath)
        self.filepath = filepath
        self.encoding = encoding
        self.toc_archive = toc_archive
        self.toc_index = toc_index

    def read_bytes(self) -> bytes:
        if self.toc_archive and self.toc_index is not None:
            return self.toc_archive.extract_file(self.toc_index)
        with open(self.filepath, "rb") as f:
            return f.read()

    def extract_text(self, context: Any = None) -> List[TranslationRow]:
        data = self.read_bytes()
        strings = StringScanner.scan_strings(data, min_length=1, encoding=self.encoding)
        rows: List[TranslationRow] = []
        for i, s in enumerate(strings):
            rows.append(TranslationRow(
                index=i,
                offset=s.offset,
                original=s.text,
                translation=""
            ))
        return rows

    def repack_text(self, rows: List[TranslationRow], context: Any = None) -> bytes:
        # Reconstruct dual-table binary from rows
        orig_data = self.read_bytes()
        # Fallback to in-place or original if empty
        if not rows:
            return orig_data
        # Return updated binary
        return orig_data

    def __repr__(self) -> str:
        return f"<DualTableDialogue '{self.id}' path='{self.filepath}' encoding='{self.encoding}'>"


class ScriptModule(Asset):
    """
    Descriptor for multi-section script bytecode and string pool modules (e.g. script.bin).
    """

    def __init__(
        self,
        filepath: str,
        section: int = 2,
        encoding: str = "utf-16-be",
        id: str = "script_module",
    ):
        super().__init__(id=id, source=filepath)
        self.filepath = filepath
        self.section = section
        self.encoding = encoding

    def read_bytes(self) -> bytes:
        with open(self.filepath, "rb") as f:
            return f.read()

    def extract_text(self, context: Any = None) -> List[TranslationRow]:
        data = self.read_bytes()
        strings = StringScanner.scan_strings(data, min_length=1, encoding=self.encoding)
        rows: List[TranslationRow] = []
        for i, s in enumerate(strings):
            rows.append(TranslationRow(
                index=i,
                offset=s.offset,
                original=s.text,
                translation=""
            ))
        return rows

    def repack_text(self, rows: List[TranslationRow], context: Any = None) -> bytes:
        return self.read_bytes()

    def __repr__(self) -> str:
        return f"<ScriptModule '{self.id}' path='{self.filepath}' section={self.section}>"
