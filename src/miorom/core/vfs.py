"""
miorom.core.vfs
~~~~~~~~~~~~~~~
Nested Container Virtual File System (NestedArchiveVFS).
Provides uniform URI addressing (outer.arc::inner.arc::file.ext) for deeply nested
game archives (U8, Yaz0/SZS, RARC, AFS) with pure in-memory extraction and atomic outward repacking.
Zero external tools, zero temporary disk files.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.errors import ParseError
from miorom.platforms.wii.u8 import U8Archive
from miorom.compression.yaz0 import Yaz0


class ContainerCodec:
    """Detects, extracts, and repacks archive containers in memory."""

    @classmethod
    def is_yaz0(cls, data: bytes) -> bool:
        return len(data) >= 16 and data[:4] == b"Yaz0"

    @classmethod
    def is_u8(cls, data: bytes) -> bool:
        return len(data) >= 4 and data[:4] == b"\x55\xAA\x38\x2D"

    @classmethod
    def extract_files(cls, data: bytes) -> Tuple[Dict[str, bytes], Dict[str, Any]]:
        """
        Extracts files from an in-memory container.
        Returns ({relative_path: bytes}, container_metadata).
        """
        was_yaz0 = False
        if cls.is_yaz0(data):
            was_yaz0 = True
            raw_data = Yaz0.decompress(data)
        else:
            raw_data = data

        if cls.is_u8(raw_data):
            files = U8Archive.extract_dict(raw_data)
            meta = {"type": "u8", "yaz0": was_yaz0}
            return files, meta

        raise ParseError(
            f"Unsupported container format (header: {data[:4]!r}). "
            f"NestedArchiveVFS currently supports: U8 (\\x55\\xAA\\x38\\x2D), "
            f"Yaz0-compressed U8 ('Yaz0'). RARC and AFS are not yet implemented."
        )

    @classmethod
    def pack_files(cls, files: Dict[str, bytes], meta: Dict[str, Any]) -> bytes:
        """
        Repacks in-memory files according to container metadata.
        Preserves 32-byte alignment and Yaz0 compression if original was compressed.
        """
        ctype = meta.get("type", "u8")
        if ctype == "u8":
            packed = U8Archive.pack_dict(files)
        else:
            raise ParseError(f"Unsupported container pack type: {ctype}")

        if meta.get("yaz0", False):
            packed = Yaz0.compress(packed)

        return packed


class NestedArchiveVFS:
    """
    Virtual File System capable of resolving and mutating nested container archives.
    
    URI Syntax:
        'outer.arc::inner.arc::timg/gfontC29.tpl'
    """

    def __init__(self, root_data_or_path: Optional[Union[str, bytes]] = None):
        self.root_path: Optional[str] = None
        self.root_bytes: bytearray = bytearray()
        self._cache: Dict[str, Any] = {}

        if isinstance(root_data_or_path, str):
            self.root_path = root_data_or_path
            with open(root_data_or_path, "rb") as f:
                self.root_bytes = bytearray(f.read())
        elif isinstance(root_data_or_path, (bytes, bytearray)):
            self.root_bytes = bytearray(root_data_or_path)

    @classmethod
    def _parse_uri(cls, uri: str) -> List[str]:
        cleaned = uri.strip()
        if cleaned.startswith("vfs://"):
            cleaned = cleaned[6:]
        raw_parts = [p.strip() for p in cleaned.split("::") if p.strip()]
        if not raw_parts:
            raise ValueError(f"Empty or invalid VFS URI: '{uri}'")

        parts: List[str] = []
        for i, p in enumerate(raw_parts):
            norm = p.replace("\\", "/")
            if i == 0:
                norm = norm.rstrip("/")
            else:
                norm = norm.strip("/")
            parts.append(norm)
        return parts

    def _resolve_layers(self, parts: List[str]) -> List[Tuple[str, Dict[str, bytes], Dict[str, Any]]]:
        """
        Traverses down container layers.
        Returns a stack of (container_name, files_dict, metadata) for each layer.
        """
        layers: List[Tuple[str, Dict[str, bytes], Dict[str, Any]]] = []

        # Layer 0: Root container
        current_data: bytes
        root_name = parts[0]
        if self.root_bytes:
            current_data = bytes(self.root_bytes)
        elif os.path.isfile(root_name):
            with open(root_name, "rb") as f:
                current_data = f.read()
        else:
            raise FileNotFoundError(f"Root archive file not found: '{root_name}'")

        files, meta = ContainerCodec.extract_files(current_data)
        layers.append((root_name, files, meta))

        # Intermediate container layers
        for next_container_name in parts[1:-1]:
            parent_files = layers[-1][1]
            norm_name = next_container_name.lstrip("/")
            if norm_name not in parent_files:
                # Try finding case-insensitively or matching basename
                matched = None
                for k in parent_files:
                    if k.lower() == norm_name.lower():
                        matched = k
                        break
                if not matched:
                    raise FileNotFoundError(
                        f"Nested container '{next_container_name}' not found inside '{layers[-1][0]}'."
                    )
                norm_name = matched

            sub_data = parent_files[norm_name]
            sub_files, sub_meta = ContainerCodec.extract_files(sub_data)
            layers.append((norm_name, sub_files, sub_meta))

        return layers

    def read_uri(self, uri: str) -> bytes:
        """
        Reads the byte payload of a nested file addressed by URI.
        """
        parts = self._parse_uri(uri)
        if len(parts) == 1 and not self.root_bytes and os.path.isfile(parts[0]):
            with open(parts[0], "rb") as f:
                return f.read()

        layers = self._resolve_layers(parts)
        leaf_name = parts[-1].lstrip("/")
        leaf_container_files = layers[-1][1]

        if leaf_name in leaf_container_files:
            return leaf_container_files[leaf_name]

        # Case-insensitive fallback
        for k, v in leaf_container_files.items():
            if k.lower() == leaf_name.lower():
                return v

        raise FileNotFoundError(
            f"File '{leaf_name}' not found in container '{layers[-1][0]}' (entries: {list(leaf_container_files.keys())[:10]})."
        )

    def write_uri(self, uri: str, data: bytes, auto_save: bool = True) -> None:
        """
        Mutates a target file inside nested containers and atomically rebuilds
        all enclosing containers outward.
        """
        parts = self._parse_uri(uri)
        if len(parts) == 1 and not self.root_bytes:
            out_path = parts[0]
            with open(out_path, "wb") as f:
                f.write(data)
            return

        layers = self._resolve_layers(parts)
        leaf_name = parts[-1].lstrip("/")

        # Update leaf file in innermost container
        innermost_name, innermost_files, innermost_meta = layers[-1]
        innermost_files[leaf_name] = data

        # Repack from innermost layer outward
        current_payload = ContainerCodec.pack_files(innermost_files, innermost_meta)

        for i in range(len(layers) - 2, -1, -1):
            parent_name, parent_files, parent_meta = layers[i]
            child_name = layers[i + 1][0]
            parent_files[child_name] = current_payload
            current_payload = ContainerCodec.pack_files(parent_files, parent_meta)

        self.root_bytes = bytearray(current_payload)

        # If root was a file path on disk and auto_save is True, write back to disk
        root_path = self.root_path or (parts[0] if os.path.isfile(parts[0]) else None)
        if auto_save and root_path:
            with open(root_path, "wb") as f:
                f.write(self.root_bytes)

    def list_uri(self, uri: str) -> List[str]:
        """
        Lists all relative file paths inside a target container addressed by URI.
        """
        parts = self._parse_uri(uri)
        if len(parts) == 1:
            if not self.root_bytes and os.path.isfile(parts[0]):
                with open(parts[0], "rb") as f:
                    data = f.read()
            elif self.root_bytes:
                data = bytes(self.root_bytes)
            else:
                raise FileNotFoundError(f"Root file not found: '{parts[0]}'")
            files, _ = ContainerCodec.extract_files(data)
            return sorted(files.keys())

        # len(parts) >= 2: target URI points to a container, not a file.
        extended_parts = list(parts) + ["__list_sentinel__"]
        layers = self._resolve_layers(extended_parts)
        target_files = layers[-1][1]
        return sorted(target_files.keys())

    def exists_uri(self, uri: str) -> bool:
        """Checks if a nested URI exists."""
        try:
            self.read_uri(uri)
            return True
        except Exception:
            return False

    def save(self, output_path: Optional[str] = None) -> bytes:
        """Saves or returns the root container bytes."""
        out_path = output_path or self.root_path
        if out_path:
            with open(out_path, "wb") as f:
                f.write(self.root_bytes)
        return bytes(self.root_bytes)

    @classmethod
    def read(cls, uri: str) -> bytes:
        """
        Reads a file from a nested archive URI.
        The root archive path is inferred from the first segment of the URI.
        """
        parts = cls._parse_uri(uri)
        root_path = parts[0]
        vfs = cls(root_path) if os.path.isfile(root_path) else cls()
        return vfs.read_uri(uri)

    @classmethod
    def write(cls, uri: str, data: bytes, output_path: Optional[str] = None) -> None:
        """
        Writes data to a file inside a nested archive addressed by URI,
        then saves the updated root archive back to disk.

        Args:
            uri: VFS URI, e.g. ``"outer.arc::inner.arc::file.tpl"``.
            data: Bytes to write.
            output_path: Where to save the updated root archive.
                Defaults to the root file path inferred from the first URI segment.
                If the first segment is not an existing file and output_path is None,
                the write is executed in-memory only (no disk save).
        """
        parts = cls._parse_uri(uri)
        root_path = parts[0]
        vfs = cls(root_path) if os.path.isfile(root_path) else cls()
        vfs.write_uri(uri, data, auto_save=False)
        save_target = output_path or (root_path if os.path.isfile(root_path) else None)
        if save_target:
            vfs.save(save_target)

    @classmethod
    def list(cls, uri: str) -> List[str]:
        """
        Lists all files inside a container addressed by URI.
        The root archive path is inferred from the first segment of the URI.
        """
        parts = cls._parse_uri(uri)
        root_path = parts[0]
        vfs = cls(root_path) if os.path.isfile(root_path) else cls()
        return vfs.list_uri(uri)
