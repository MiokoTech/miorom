import struct
from typing import Optional


class PSXExe:
    """
    PlayStation 1 (PS-X) Executable binary header parser and builder.
    """

    MAGIC = b"PS-X EXE"
    HEADER_SIZE = 2048

    def __init__(self, data: bytes):
        if len(data) < self.HEADER_SIZE:
            raise ValueError("Data too small for PS-X EXE header (minimum 2048 bytes).")

        if data[:8] != self.MAGIC:
            raise ValueError(f"Invalid PS-X EXE magic: {data[:8]!r}")

        self.initial_pc = struct.unpack_from("<I", data, 0x10)[0]
        self.initial_gp = struct.unpack_from("<I", data, 0x14)[0]
        self.text_ram_address = struct.unpack_from("<I", data, 0x18)[0]
        self.text_size = struct.unpack_from("<I", data, 0x1C)[0]
        self.initial_sp = struct.unpack_from("<I", data, 0x30)[0]

        self.text_data = bytearray(data[self.HEADER_SIZE : self.HEADER_SIZE + self.text_size])

    @classmethod
    def from_file(cls, path: str) -> "PSXExe":
        with open(path, "rb") as f:
            return cls(f.read())

    def to_bytes(self) -> bytes:
        header = bytearray(self.HEADER_SIZE)
        header[0:8] = self.MAGIC
        struct.pack_into("<I", header, 0x10, self.initial_pc)
        struct.pack_into("<I", header, 0x14, self.initial_gp)
        struct.pack_into("<I", header, 0x18, self.text_ram_address)
        struct.pack_into("<I", header, 0x1C, len(self.text_data))
        struct.pack_into("<I", header, 0x30, self.initial_sp)
        return bytes(header + self.text_data)
