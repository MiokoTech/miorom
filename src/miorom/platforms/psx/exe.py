
from miorom.core.schema import U32, BinaryStruct, FixedString, RawBytes
from miorom.errors import ParseError


class PSXExeHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = FixedString(8)
    _reserved_0x08 = RawBytes(8)
    initial_pc = U32()
    initial_gp = U32()
    text_ram_address = U32()
    text_size = U32()
    _reserved_0x20 = RawBytes(16)
    initial_sp = U32()
    _reserved_0x34 = RawBytes(0x7CC)


class PSXExe:
    """
    PlayStation 1 (PS-X) Executable binary header parser and builder.
    """

    MAGIC = b"PS-X EXE"
    HEADER_SIZE = 2048

    def __init__(self, data: bytes):
        if len(data) < self.HEADER_SIZE:
            raise ParseError("Data too small for PS-X EXE header (minimum 2048 bytes).")

        if data[:8] != self.MAGIC:
            raise ParseError(f"Invalid PS-X EXE magic: {data[:8]!r}")

        self._header = PSXExeHeaderStruct.from_bytes(data, offset=0)
        self.initial_pc = self._header.initial_pc
        self.initial_gp = self._header.initial_gp
        self.text_ram_address = self._header.text_ram_address
        self.text_size = self._header.text_size
        self.initial_sp = self._header.initial_sp

        self.text_data = bytearray(data[self.HEADER_SIZE : self.HEADER_SIZE + self.text_size])

    @classmethod
    def from_file(cls, path: str) -> "PSXExe":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def pc(self) -> int:
        return self.initial_pc

    @pc.setter
    def pc(self, val: int) -> None:
        self.initial_pc = val

    @property
    def gp(self) -> int:
        return self.initial_gp

    @gp.setter
    def gp(self, val: int) -> None:
        self.initial_gp = val

    @property
    def t_addr(self) -> int:
        return self.text_ram_address

    @t_addr.setter
    def t_addr(self, val: int) -> None:
        self.text_ram_address = val

    @property
    def t_size(self) -> int:
        return len(self.text_data)

    @t_size.setter
    def t_size(self, val: int) -> None:
        self.text_size = val

    @property
    def sp_base(self) -> int:
        return self.initial_sp

    @sp_base.setter
    def sp_base(self, val: int) -> None:
        self.initial_sp = val

    def to_bytes(self) -> bytes:
        self._header.magic = self.MAGIC
        self._header.initial_pc = self.initial_pc
        self._header.initial_gp = self.initial_gp
        self._header.text_ram_address = self.text_ram_address
        self._header.text_size = len(self.text_data)
        self._header.initial_sp = self.initial_sp
        header = bytearray(self._header.to_bytes())
        return bytes(header + self.text_data)
