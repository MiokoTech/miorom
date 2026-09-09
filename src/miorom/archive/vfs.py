import os
from typing import Dict, Generator, List, Optional, Tuple, Union

from miorom.archive.container import ArchiveContainer, ArchiveEntry


from miorom.errors import ParseError

class VFSNode:
    """Base class for any virtual file system node."""

    def __init__(self, name: str, is_dir: bool = False):
        self.name = name
        self.is_dir = is_dir
        self.parent: Optional["VFSDirectory"] = None

    @property
    def path(self) -> str:
        if self.parent is None:
            return "/" if self.is_dir else f"/{self.name}"
        parent_path = self.parent.path
        if parent_path == "/":
            return f"/{self.name}"
        return f"{parent_path}/{self.name}"


class VFSFile(VFSNode):
    """Virtual file backed by in-memory byte buffer."""

    def __init__(self, name: str, data: bytes = b""):
        super().__init__(name, is_dir=False)
        self.data: bytearray = bytearray(data)

    @property
    def size(self) -> int:
        return len(self.data)

    def read(self, offset: int = 0, length: Optional[int] = None) -> bytes:
        if length is None:
            return bytes(self.data[offset:])
        return bytes(self.data[offset:offset + length])

    def write(self, new_data: bytes, offset: int = 0):
        end_offset = offset + len(new_data)
        if end_offset > len(self.data):
            self.data.extend(b"\x00" * (end_offset - len(self.data)))
        self.data[offset:end_offset] = new_data

    def set_content(self, new_data: bytes):
        self.data = bytearray(new_data)


class VFSDirectory(VFSNode):
    """Virtual directory containing child files and subdirectories."""

    def __init__(self, name: str):
        super().__init__(name, is_dir=True)
        self.children: Dict[str, VFSNode] = {}

    def add(self, node: VFSNode):
        node.parent = self
        self.children[node.name] = node

    def get(self, name: str) -> Optional[VFSNode]:
        return self.children.get(name)

    def remove(self, name: str) -> Optional[VFSNode]:
        node = self.children.pop(name, None)
        if node:
            node.parent = None
        return node

    def list(self) -> List[str]:
        return sorted(self.children.keys())


class VirtualFileSystem:
    """
    In-memory hierarchical Virtual File System (VFS).
    Supports mounting archive containers, navigating nested directory trees,
    in-place binary editing, and exporting/importing to physical disk.
    """

    def __init__(self):
        self.root = VFSDirectory("")

    @staticmethod
    def _split_path(path: str) -> List[str]:
        cleaned = path.replace("\\", "/").strip("/")
        if not cleaned:
            return []
        parts = [p for p in cleaned.split("/") if p and p != "."]
        resolved: List[str] = []
        for p in parts:
            if p == "..":
                if resolved:
                    resolved.pop()
            else:
                resolved.append(p)
        return resolved

    def resolve(self, path: str) -> Optional[VFSNode]:
        """Resolve a path string to a VFSNode, or None if not found."""
        parts = self._split_path(path)
        if not parts:
            return self.root

        current: VFSNode = self.root
        for part in parts:
            if not current.is_dir or not isinstance(current, VFSDirectory):
                return None
            child = current.get(part)
            if child is None:
                return None
            current = child
        return current

    def exists(self, path: str) -> bool:
        return self.resolve(path) is not None

    def is_file(self, path: str) -> bool:
        node = self.resolve(path)
        return node is not None and not node.is_dir

    def is_dir(self, path: str) -> bool:
        node = self.resolve(path)
        return node is not None and node.is_dir

    def mkdir(self, path: str, exist_ok: bool = True) -> VFSDirectory:
        """Create directory path recursively."""
        parts = self._split_path(path)
        current = self.root
        for part in parts:
            child = current.get(part)
            if child is None:
                new_dir = VFSDirectory(part)
                current.add(new_dir)
                current = new_dir
            elif child.is_dir and isinstance(child, VFSDirectory):
                current = child
            else:
                raise NotADirectoryError(f"Path component '{part}' is a file, not a directory.")
        return current

    def open(self, path: str, mode: str = "rb") -> VFSFile:
        """Open or create a virtual file."""
        node = self.resolve(path)
        if node is not None:
            if node.is_dir:
                raise IsADirectoryError(f"'{path}' is a directory.")
            assert isinstance(node, VFSFile)
            if "w" in mode:
                node.truncate(0)
            return node

        # If writing, create parents and file
        if "w" in mode or "a" in mode or "+" in mode:
            parts = self._split_path(path)
            if not parts:
                raise ParseError("Cannot open root as a file.")
            filename = parts[-1]
            parent_path = "/".join(parts[:-1])
            parent_dir = self.mkdir(parent_path, exist_ok=True)
            new_file = VFSFile(filename, b"")
            parent_dir.add(new_file)
            return new_file

        raise FileNotFoundError(f"File not found: '{path}'")

    def read(self, path: str) -> bytes:
        """Read entire content of a virtual file."""
        f = self.open(path, "rb")
        return f.read()

    def write(self, path: str, data: bytes, create_parents: bool = True):
        """Write content into a virtual file, creating parent directories if needed."""
        parts = self._split_path(path)
        if not parts:
            raise ParseError("Invalid file path.")
        filename = parts[-1]
        parent_path = "/".join(parts[:-1])

        parent = self.mkdir(parent_path, exist_ok=True) if create_parents else self.resolve(parent_path)
        if parent is None or not isinstance(parent, VFSDirectory):
            raise FileNotFoundError(f"Parent directory does not exist: '{parent_path}'")

        existing = parent.get(filename)
        if existing is not None:
            if existing.is_dir:
                raise IsADirectoryError(f"'{path}' is a directory.")
            assert isinstance(existing, VFSFile)
            existing.set_content(data)
        else:
            parent.add(VFSFile(filename, data))

    def list_dir(self, path: str = "/") -> List[str]:
        """List children of a directory."""
        node = self.resolve(path)
        if node is None:
            raise FileNotFoundError(f"Directory not found: '{path}'")
        if not node.is_dir or not isinstance(node, VFSDirectory):
            raise NotADirectoryError(f"'{path}' is not a directory.")
        return node.list()

    def remove(self, path: str):
        """Remove a file or empty directory."""
        parts = self._split_path(path)
        if not parts:
            raise ParseError("Cannot remove root directory.")
        filename = parts[-1]
        parent_path = "/".join(parts[:-1])
        parent = self.resolve(parent_path)
        if parent is None or not isinstance(parent, VFSDirectory):
            raise FileNotFoundError(f"Parent not found for '{path}'")
        node = parent.get(filename)
        if node is None:
            raise FileNotFoundError(f"Node not found: '{path}'")
        if node.is_dir and isinstance(node, VFSDirectory) and node.children:
            raise OSError(f"Directory not empty: '{path}'")
        parent.remove(filename)

    def walk(self, path: str = "/") -> Generator[Tuple[str, List[str], List[str]], None, None]:
        """Generate file and directory names in a directory tree (similar to os.walk)."""
        node = self.resolve(path)
        if node is None or not isinstance(node, VFSDirectory):
            return

        dirs: List[str] = []
        files: List[str] = []
        for name, child in node.children.items():
            if child.is_dir:
                dirs.append(name)
            else:
                files.append(name)

        yield (node.path, dirs, files)

        for d in dirs:
            child_dir = node.get(d)
            if child_dir and isinstance(child_dir, VFSDirectory):
                yield from self.walk(child_dir.path)

    def mount(
        self,
        mount_point: str,
        source: Union[ArchiveContainer, Dict[str, bytes], "VirtualFileSystem"],
    ):
        """
        Mount an ArchiveContainer, a dictionary of {path: bytes}, or another VFS
        into the specified mount point path.
        """
        target_dir = self.mkdir(mount_point, exist_ok=True)

        if isinstance(source, ArchiveContainer):
            for entry in source.entries:
                if entry.data is not None:
                    entry_path = f"{mount_point}/{entry.name}"
                    self.write(entry_path, entry.data, create_parents=True)

        elif isinstance(source, dict):
            for rel_path, data in source.items():
                full_path = f"{mount_point}/{rel_path.lstrip('/')}"
                self.write(full_path, data, create_parents=True)

        elif isinstance(source, VirtualFileSystem):
            for dirpath, _, files in source.walk("/"):
                rel_base = dirpath.lstrip("/")
                for f_name in files:
                    file_src_path = f"{dirpath}/{f_name}" if dirpath != "/" else f"/{f_name}"
                    data = source.read(file_src_path)
                    dest_path = f"{mount_point}/{rel_base}/{f_name}".replace("//", "/")
                    self.write(dest_path, data, create_parents=True)

    def export_to_disk(self, target_dir: str):
        """Export the complete virtual filesystem into a physical directory."""
        os.makedirs(target_dir, exist_ok=True)
        for dirpath, dirs, files in self.walk("/"):
            rel_dir = dirpath.lstrip("/")
            phys_dir = os.path.join(target_dir, rel_dir)
            os.makedirs(phys_dir, exist_ok=True)
            for f_name in files:
                v_path = f"{dirpath}/{f_name}" if dirpath != "/" else f"/{f_name}"
                data = self.read(v_path)
                with open(os.path.join(phys_dir, f_name), "wb") as f:
                    f.write(data)

    def import_from_disk(self, source_dir: str):
        """Recursively import files and folders from a physical directory into the VFS."""
        for root, dirs, files in os.walk(source_dir):
            rel_path = os.path.relpath(root, source_dir)
            if rel_path == ".":
                rel_path = ""
            for f_name in files:
                phys_file = os.path.join(root, f_name)
                with open(phys_file, "rb") as f:
                    content = f.read()
                v_path = f"/{rel_path}/{f_name}".replace("//", "/")
                self.write(v_path, content, create_parents=True)

    def to_archive_container(self) -> ArchiveContainer:
        """Convert all virtual files in this VFS into an ArchiveContainer."""
        entries: List[ArchiveEntry] = []
        idx = 0
        for dirpath, _, files in self.walk("/"):
            rel_dir = dirpath.lstrip("/")
            for f_name in sorted(files):
                v_path = f"{dirpath}/{f_name}" if dirpath != "/" else f"/{f_name}"
                data = self.read(v_path)
                rel_entry_name = f"{rel_dir}/{f_name}".lstrip("/")
                entries.append(
                    ArchiveEntry(
                        index=idx,
                        name=rel_entry_name,
                        offset=0,
                        size=len(data),
                        data=data,
                    )
                )
                idx += 1
        return ArchiveContainer(entries)
