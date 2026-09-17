"""
miorom.text.bmg
~~~~~~~~~~~~~~~
Nintendo BMG (Binary Message) Parser and Builder.
Standard dialogue and text container for Nintendo GameCube and Wii titles
(e.g., Mario Kart Wii, Super Paper Mario, The Legend of Zelda: Twilight Princess).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import U8, U16, U32, BinaryStruct, Padding, RawBytes
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

    def __init__(
        self,
        messages: Optional[List[BMGMessage]] = None,
        encoding: int = 2,
        file_id: int = 0,
        default_color: int = 0,
        inf_entry_size: Optional[int] = None,
    ):
        self.messages = list(messages or [])
        self.encoding = encoding  # default UTF-16BE (2)
        self.file_id = file_id
        self.default_color = default_color
        self.inf_entry_size = inf_entry_size

    @classmethod
    def from_bytes(cls, data: bytes) -> BMGFile:
        if len(data) < BMGHeaderStruct.sizeof() or data[:8] != cls.MAGIC:
            raise ParseError("Invalid BMG header or magic.")

        header = BMGHeaderStruct.from_bytes(data, offset=0)
        enc_byte = header.encoding
        enc_str = {1: "cp1252", 2: "utf-16-be", 3: "shift_jis", 4: "utf-8"}.get(enc_byte, "utf-16-be")

        pos = BMGHeaderStruct.sizeof()
        inf1_entries: List[int] = []
        inf1_attributes: List[bytes] = []
        dat1_data = b""
        mid1_ids: List[int] = []
        file_id = 0
        default_color = 0
        inf_entry_size: Optional[int] = None

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
                inf_entry_size = inf_hdr.entry_size
                file_id = inf_hdr.file_id
                default_color = inf_hdr.default_color
                for _ in range(inf_hdr.entry_count):
                    if sec_reader.remaining >= 4:
                        str_off = sec_reader.read_u32()
                        inf1_entries.append(str_off)
                        attr_len = inf_hdr.entry_size - 4
                        if attr_len > 0 and sec_reader.remaining >= attr_len:
                            attr_bytes = sec_reader.read_bytes(attr_len)
                        elif attr_len > 0:
                            attr_bytes = sec_reader.read_bytes(sec_reader.remaining)
                        else:
                            attr_bytes = b""
                        inf1_attributes.append(attr_bytes)
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
            mid = mid1_ids[idx] if idx < len(mid1_ids) else None
            attr = inf1_attributes[idx] if idx < len(inf1_attributes) else b""
            if offset >= len(dat1_data) or offset < 0:
                messages.append(BMGMessage(text="", message_id=mid, attributes=attr))
                continue

            if enc_byte == 2:  # UTF-16BE
                curr_t = offset
                while curr_t + 1 < len(dat1_data):
                    if dat1_data[curr_t : curr_t + 2] == b"\x00\x00":
                        break
                    # BMG escape sequence in UTF-16BE: 0x001A followed by 1-byte total length
                    if dat1_data[curr_t : curr_t + 2] == b"\x00\x1a" and curr_t + 2 < len(dat1_data):
                        seq_len = dat1_data[curr_t + 2]
                        if seq_len >= 3:
                            curr_t += seq_len
                            # Maintain 2-byte alignment for UTF-16BE code units
                            if (curr_t - offset) % 2 != 0:
                                curr_t += 1
                            continue
                    curr_t += 2
                s_bytes = dat1_data[offset:curr_t]
                text = s_bytes.decode(enc_str, errors="replace")
            else:
                curr_t = offset
                while curr_t < len(dat1_data):
                    if dat1_data[curr_t] == 0:
                        break
                    # BMG escape sequence in 8-bit encodings: 0x1A followed by 1-byte total length
                    if dat1_data[curr_t] == 0x1A and curr_t + 1 < len(dat1_data):
                        seq_len = dat1_data[curr_t + 1]
                        if seq_len >= 2:
                            curr_t += seq_len
                            continue
                    curr_t += 1
                s_bytes = dat1_data[offset:curr_t]
                text = s_bytes.decode(enc_str, errors="replace")

            messages.append(BMGMessage(text=text, message_id=mid, attributes=attr))

        return cls(
            messages=messages,
            encoding=enc_byte,
            file_id=file_id,
            default_color=default_color,
            inf_entry_size=inf_entry_size,
        )

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

        # 2. Build INF1 Section (Offsets Table & Attributes)
        if self.inf_entry_size is not None:
            entry_size = max(4, self.inf_entry_size)
        else:
            max_attr_len = max((len(m.attributes) for m in self.messages), default=0)
            if max_attr_len > 0:
                entry_size = 4 + max(4, max_attr_len)
            else:
                entry_size = 8

        attr_slot_size = entry_size - 4

        inf_body = BinaryWriter(endian=">")
        inf_body.write_bytes(
            BMGINF1HeaderStruct(
                entry_count=len(self.messages),
                entry_size=entry_size,
                file_id=self.file_id,
                default_color=self.default_color,
            ).to_bytes()
        )
        for i, off in enumerate(offsets):
            inf_body.write_u32(off)
            if attr_slot_size > 0:
                msg = self.messages[i] if i < len(self.messages) else None
                attr_data = msg.attributes if msg and msg.attributes else b""
                inf_body.write_bytes(attr_data.ljust(attr_slot_size, b"\x00")[:attr_slot_size])

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
