"""
miorom.signature_db
~~~~~~~~~~~~~~~~~~~
Signature Database System (like IDA FLIRT / Ghidra FID) — pure pattern matching.
Stores SignaturePattern entries with function metadata in a portable .miosig file.
Enables mass auto-labeling of SDK boilerplate functions in binary analysis.
"""

from miorom.result import MioRomResult
import json
import importlib.metadata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.core.signatures import SignaturePattern, SignatureScanner


@dataclass
class SignatureEntry(MioRomResult):
    """A single function signature with metadata."""
    name: str
    pattern: str          # hex pattern string with ?? wildcards
    source_sdk: str = ""  # e.g. "devkitARM", "libultra", "PsyQ"
    version: str = ""     # e.g. "v1.0", "SDK 2.4"
    arch: str = ""        # e.g. "arm", "mips", "ppc"


class SignatureDatabase:
    """
    Portable signature database (.miosig JSON format).

    Usage:
        db = SignatureDatabase.load("n64_sdk.miosig")
        matches = db.scan(rom_data, base_address=0x80000000)
        for addr, entry, confidence in matches:
            print(f"  {addr:08X}: {entry.name} ({entry.source_sdk})")
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.entries: List[SignatureEntry] = []
        self._load_plugin_databases()

    def _load_plugin_databases(self) -> None:
        """Auto-load third-party signature databases via entry_points."""
        try:
            eps = importlib.metadata.entry_points(group="miorom.signature_databases")
        except TypeError:
            return
        for entry_point in eps:
            try:
                provider = entry_point.load()
                if callable(provider):
                    provider = provider()
                entries = getattr(provider, "entries", None)
                if entries is None and callable(provider):
                    entries = provider()
                for entry in entries or []:
                    self.entries.append(SignatureEntry(**entry) if isinstance(entry, dict) else entry)
            except Exception:
                continue

    def add(self, entry: SignatureEntry) -> None:
        self.entries.append(entry)

    def save(self, path: Optional[str] = None) -> str:
        target = path or self.path or "signatures.miosig"
        data = {
            "version": 1,
            "entries": [
                {
                    "name": e.name,
                    "pattern": e.pattern,
                    "source_sdk": e.source_sdk,
                    "version": e.version,
                    "arch": e.arch,
                }
                for e in self.entries
            ],
        }
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return target

    @classmethod
    def load(cls, path: str) -> "SignatureDatabase":
        db = cls(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for e in data.get("entries", []):
            db.entries.append(SignatureEntry(**e))
        return db

    def scan(self, data: bytes, base_address: int = 0) -> List[Tuple[int, SignatureEntry, float]]:
        """
        Scan binary data against all registered patterns.
        Returns list of (offset_in_data, entry, confidence) tuples.
        Confidence is currently binary (1.0 or 0.0) — exact pattern match.
        """
        results = []
        for entry in self.entries:
            try:
                pattern = SignaturePattern(entry.pattern)
                matches = pattern.find_all(data)
                for offset in matches:
                    results.append((base_address + offset, entry, 1.0))
            except Exception:
                continue
        return results


class SignatureBuilder:
    """
    Generate signatures from known binary code (e.g. SDK .o files, library dumps).

    Usage:
        builder = SignatureBuilder()
        sig = builder.from_function(code_bytes, name="memcpy", sdk="devkitARM")
        # 16 leading bytes + ?? wildcard tail for reliable matching
        print(sig.pattern)
    """

    @staticmethod
    def from_function(code_bytes: bytes, name: str, sdk: str = "", arch: str = "",
                      min_prologue: int = 16) -> SignatureEntry:
        """
        Create a signature from a function's prologue bytes.
        Uses first `min_prologue` bytes (or full function if shorter).
        Adds trailing ?? wildcards for minor compiler version tolerance.
        """
        prologue = code_bytes[:min_prologue]
        pattern = " ".join(f"{b:02X}" for b in prologue)
        if len(code_bytes) > min_prologue:
            pattern += " ?? ??"
        return SignatureEntry(
            name=name,
            pattern=pattern,
            source_sdk=sdk,
            arch=arch,
        )
