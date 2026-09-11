"""
miorom.text.bmg
~~~~~~~~~~~~~~~
Nintendo BMG (Binary Message) Parser and Builder.
Standard dialogue and text container for Nintendo GameCube and Wii titles
(e.g., Mario Kart Wii, Super Paper Mario, The Legend of Zelda: Twilight Princess).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, Padding, RawBytes, U8, U16, U32
from miorom.errors import ParseError
from miorom.result import MioRomResult


class BMGHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(8)  # b"MESGbmg1"
    file_size = U32()
    section_count = U32()
    encoding = U8()      # 1 = CP1252, 2 = UTF-16BE, 3 = Shift-JIS, 4 = UTF-8
    _reserved = Padding(15)


class BMGSectionHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)  # b"INF1", b"DAT1", b"MID1"
    size = U32()


class BMGINF1HeaderStruct(BinaryStruct):
    _endian = ">"
    entry_count = U16()
    entry_size = U16()
    file_id = U16()
    default_color = U8()
    _reserved = Padding(1)


class BMGMID1HeaderStruct(BinaryStruct):
    _endian = ">"
    entry_count = U16()
    format = U8()
    info = U8()
    _reserved = Padding(4)


@dataclass
class BMGMessage(MioRomResult):
    """Individual dialogue line or system string in a BMG container."""
    text: str
    message_id: Optional[int] = None
    attributes: bytes = b""


class BMGFile:
    """
    Nintendo BMG dialogue resource container reader and writer.
    Handles INF1 offset tables, DAT1 string pools, and optional MID1 Message ID mappings.
    Pure Python, using MioROM declarative binary primitives.
    """

    MAGIC = b"MESGbmg1"

    def __init__(self, messages: Optional[List[BMGMessage]] = None, encoding: int = 2):
        self.messages = list(messages or [])
        self.encoding = encoding  # default UTF-16BE (2)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BMGFile":
        if len(data) < BMGHeaderStruct.sizeof() or data[:8] != cls.MAGIC:
            raise ParseError("Invalid BMG header or magic.")

        header = BMGHeaderStruct.from_bytes(data, offset=0)
        enc_byte = header.encoding
        enc_str = {1: "cp1252", 2: "utf-16-be", 3: "shift_jis", 4: "utf-8"}.get(enc_byte, "utf-16-be")

        pos = BMGHeaderStruct.sizeof()
        inf1_entries: List[int] = []
        dat1_data = b""
        mid1_ids: List[int] = []

        for _ in range(header.section_count):
            if pos + BMGSectionHeaderStruct.sizeof() > len(data):
                break
            sec_header = BMGSectionHeaderStruct.from_bytes(data, offset=pos)
            sec_size = sec_header.size
            sec_magic = sec_header.magic
            sec_data = data[pos : pos + sec_size]

            sec_reader = BinaryReader(sec_data, endian=">")
            sec_reader.seek(BMGSectionHeaderStruct.sizeof())

            if sec_magic == b"INF1":
                inf_hdr = BMGINF1HeaderStruct.from_bytes(sec_data, offset=BMGSectionHeaderStruct.sizeof())
                sec_reader.seek(16)
                for _ in range(inf_hdr.entry_count):
                    if sec_reader.remaining >= 4:
                        str_off = sec_reader.read_u32()
                        inf1_entries.append(str_off)
                        if inf_hdr.entry_size > 4:
                            sec_reader.skip(inf_hdr.entry_size - 4)
            elif sec_magic == b"DAT1":
                dat1_data = sec_data[BMGSectionHeaderStruct.sizeof():]
            elif sec_magic == b"MID1":
                mid_hdr = BMGMID1HeaderStruct.from_bytes(sec_data, offset=BMGSectionHeaderStruct.sizeof())
                sec_reader.seek(16)
                for _ in range(mid_hdr.entry_count):
                    if sec_reader.remaining >= 4:
                        mid1_ids.append(sec_reader.read_u32())

            pad = (32 - (sec_size % 32)) % 32
            pos += sec_size + pad

        messages: List[BMGMessage] = []
        for idx, offset in enumerate(inf1_entries):
            if enc_byte == 2:  # UTF-16BE
                curr_t = offset
                while curr_t + 1 < len(dat1_data):
                    if dat1_data[curr_t : curr_t + 2] == b"\x00\x00":
                        break
                    curr_t += 2
                s_bytes = dat1_data[offset:curr_t]
                text = s_bytes.decode(enc_str, errors="replace")
            else:
                term = dat1_data.find(b"\x00", offset)
                if term == -1:
                    term = len(dat1_data)
                text = dat1_data[offset:term].decode(enc_str, errors="replace")

            mid = mid1_ids[idx] if idx < len(mid1_ids) else None
            messages.append(BMGMessage(text=text, message_id=mid))

        return cls(messages=messages, encoding=enc_byte)

    def to_bytes(self) -> bytes:
        """Serializes BMGFile back into Nintendo BMG binary container."""
        enc_str = {1: "cp1252", 2: "utf-16-be", 3: "shift_jis", 4: "utf-8"}.get(self.encoding, "utf-16-be")

        # 1. Build DAT1 Section (String Pool)
        dat_writer = BinaryWriter(endian=">")
        dat_writer.write_bytes(b"\x00\x00" if self.encoding == 2 else b"\x00")
        offsets: List[int] = []

        for m in self.messages:
            offsets.append(dat_writer.tell())
            dat_writer.write_bytes(m.text.encode(enc_str, errors="replace"))
            dat_writer.write_bytes(b"\x00\x00" if self.encoding == 2 else b"\x00")

        dat_body = dat_writer.to_bytes()
        dat_size = BMGSectionHeaderStruct.sizeof() + len(dat_body)

        dat_sec = BinaryWriter(endian=">")
        dat_sec.write_bytes(BMGSectionHeaderStruct(magic=b"DAT1", size=dat_size).to_bytes())
        dat_sec.write_bytes(dat_body)
        dat_sec.align(32)

        # 2. Build INF1 Section (Offsets Table)
        inf_body = BinaryWriter(endian=">")
        inf_body.write_bytes(
            BMGINF1HeaderStruct(
                entry_count=len(self.messages),
                entry_size=8,
                file_id=0,
                default_color=0,
            ).to_bytes()
        )
        for off in offsets:
            inf_body.write_u32(off)
            inf_body.write_u32(0)  # padding/attribute

        inf_body_bytes = inf_body.to_bytes()
        inf_size = BMGSectionHeaderStruct.sizeof() + len(inf_body_bytes)

        inf_sec = BinaryWriter(endian=">")
        inf_sec.write_bytes(BMGSectionHeaderStruct(magic=b"INF1", size=inf_size).to_bytes())
        inf_sec.write_bytes(inf_body_bytes)
        inf_sec.align(32)

        # 3. Build MID1 Section (Message IDs, optional)
        has_mid = any(m.message_id is not None for m in self.messages)
        mid_sec_bytes = b""
        sec_count = 2

        if has_mid:
            sec_count = 3
            mid_body = BinaryWriter(endian=">")
            mid_body.write_bytes(
                BMGMID1HeaderStruct(
                    entry_count=len(self.messages),
                    format=1,
                    info=0,
                ).to_bytes()
            )
            for i, m in enumerate(self.messages):
                mid_val = m.message_id if m.message_id is not None else i
                mid_body.write_u32(mid_val)

            mid_body_bytes = mid_body.to_bytes()
            mid_size = BMGSectionHeaderStruct.sizeof() + len(mid_body_bytes)

            mid_sec = BinaryWriter(endian=">")
            mid_sec.write_bytes(BMGSectionHeaderStruct(magic=b"MID1", size=mid_size).to_bytes())
            mid_sec.write_bytes(mid_body_bytes)
            mid_sec.align(32)
            mid_sec_bytes = mid_sec.to_bytes()

        inf_sec_bytes = inf_sec.to_bytes()
        dat_sec_bytes = dat_sec.to_bytes()
        total_file_size = BMGHeaderStruct.sizeof() + len(inf_sec_bytes) + len(dat_sec_bytes) + len(mid_sec_bytes)

        main_writer = BinaryWriter(endian=">")
        main_writer.write_bytes(
            BMGHeaderStruct(
                magic=self.MAGIC,
                file_size=total_file_size,
                section_count=sec_count,
                encoding=self.encoding,
            ).to_bytes()
        )
        main_writer.write_bytes(inf_sec_bytes)
        main_writer.write_bytes(dat_sec_bytes)
        if has_mid:
            main_writer.write_bytes(mid_sec_bytes)

        return main_writer.to_bytes()
