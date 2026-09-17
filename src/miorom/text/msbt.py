"""
miorom.text.msbt
~~~~~~~~~~~~~~~~
Nintendo MSBT (Message Studio Binary Text) Parser and Builder.
Standard dialogue container used in Nintendo Wii, NDS (late), 3DS, and Switch titles
(e.g., The Legend of Zelda: Spirit Tracks, Super Mario Galaxy, Animal Crossing).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import U8, U16, U32, BinaryStruct, Padding, RawBytes
from miorom.errors import ParseError
from miorom.result import MioRomResult


class MSBTHeaderStruct(BinaryStruct):
    magic = RawBytes(8)      # b"MsgStdBn"
    bom = RawBytes(2)        # b"\xFE\xFF" (BE) or b"\xFF\xFE" (LE)
    _pad1 = Padding(2)       # 0x0A..0x0B
    encoding = U8()          # 0x0C: 0 = UTF-8, 1 = UTF-16, 2 = UTF-32
    version = U8()           # 0x0D: typically 3
    section_count = U16()    # 0x0E..0x0F
    _pad2 = Padding(2)       # 0x10..0x11
    file_size = U32()        # 0x12..0x15
    _pad3 = Padding(10)      # 0x16..0x1F (total 32 bytes)


class MSBTSectionHeaderStruct(BinaryStruct):
    magic = RawBytes(4)      # b"LBL1", b"TXT2", etc.
    size = U32()             # section size without 16-byte header
    _reserved = Padding(8)   # 8 bytes padding (total 16 bytes)


@dataclass
class MSBTEntry(MioRomResult):
    """An individual dialogue string entry identified by a text label."""
    label: str
    text: str
    attributes: bytes = b""


class MSBTFile:
    """
    Nintendo MSBT dialogue and message catalog reader and writer.
    Encodes and decodes LBL1 (label hash table) and TXT2 (string pool) sections.
    Pure Python, using MioROM declarative binary primitives.
    """

    MAGIC = b"MsgStdBn"

    def __init__(
        self,
        entries: Optional[List[MSBTEntry]] = None,
        encoding: str = "utf-16",
        endian: str = "<",
        attribute_size: int = 0,
        other_sections: Optional[List[Tuple[bytes, bytes]]] = None,
    ):
        self.entries = list(entries or [])
        self.encoding = encoding.lower()
        self.endian = endian
        self.attribute_size = attribute_size
        self.other_sections = list(other_sections or [])

    @property
    def labels(self) -> List[str]:
        return [e.label for e in self.entries]

    def get_text(self, label: str) -> Optional[str]:
        for e in self.entries:
            if e.label == label:
                return e.text
        return None

    def set_text(self, label: str, text: str):
        for e in self.entries:
            if e.label == label:
                e.text = text
                return
        self.entries.append(MSBTEntry(label=label, text=text))

    @classmethod
    def from_bytes(cls, data: bytes) -> MSBTFile:
        if len(data) < MSBTHeaderStruct.sizeof() or data[:8] != cls.MAGIC:
            raise ParseError("Invalid MSBT header or magic.")

        bom = data[8:10]
        endian = ">" if bom == b"\xFE\xFF" else "<"

        header = MSBTHeaderStruct.from_bytes(data, offset=0, endian=endian)
        enc_code = header.encoding
        encoding = "utf-8" if enc_code == 0 else ("utf-16-be" if endian == ">" else "utf-16-le")

        pos = MSBTHeaderStruct.sizeof()
        labels: List[Tuple[str, int]] = []
        texts: List[str] = []
        attributes: List[bytes] = []
        attribute_size = 0
        other_sections: List[Tuple[bytes, bytes]] = []

        while pos + MSBTSectionHeaderStruct.sizeof() <= len(data):
            sec_hdr = MSBTSectionHeaderStruct.from_bytes(data, offset=pos, endian=endian)
            sec_magic = sec_hdr.magic
            sec_size = sec_hdr.size
            sec_start = pos + MSBTSectionHeaderStruct.sizeof()
            sec_data = data[sec_start : sec_start + sec_size]

            sec_reader = BinaryReader(sec_data, endian=endian)

            if sec_magic == b"LBL1":
                num_groups = sec_reader.read_u32()
                groups: List[Tuple[int, int]] = []
                for _ in range(num_groups):
                    count = sec_reader.read_u32()
                    g_off = sec_reader.read_u32()
                    groups.append((count, g_off))

                for count, g_off in groups:
                    sec_reader.seek(g_off)
                    for _ in range(count):
                        if sec_reader.remaining < 1:
                            break
                        l_len = sec_reader.read_u8()
                        l_name = sec_reader.read_bytes(l_len).decode("ascii", errors="replace")
                        str_idx = sec_reader.read_u32()
                        labels.append((l_name, str_idx))

            elif sec_magic == b"ATR1":
                atr_count = sec_reader.read_u32()
                atr_size = sec_reader.read_u32()
                attribute_size = atr_size
                for _ in range(atr_count):
                    if sec_reader.remaining >= atr_size:
                        attributes.append(sec_reader.read_bytes(atr_size))
                    else:
                        break

            elif sec_magic == b"TXT2":
                str_count = sec_reader.read_u32()
                offsets = [sec_reader.read_u32() for _ in range(str_count)]
                u16_field = U16(endian=endian)
                tag_magic = b"\x0e\x00" if endian == "<" else b"\x00\x0e"
                for off in offsets:
                    if off < len(sec_data):
                        if "utf-16" in encoding:
                            curr_t = off
                            while curr_t + 1 < len(sec_data):
                                if sec_data[curr_t : curr_t + 2] == b"\x00\x00":
                                    break
                                if sec_data[curr_t : curr_t + 2] == tag_magic and curr_t + 8 <= len(sec_data):
                                    arg_len = u16_field.unpack(sec_data, curr_t + 6, endian)[0]
                                    curr_t += 8 + arg_len
                                    continue
                                curr_t += 2
                            t_str = sec_data[off:curr_t].decode(encoding, errors="replace")
                        else:
                            curr_t = off
                            while curr_t < len(sec_data):
                                if sec_data[curr_t] == 0:
                                    break
                                if sec_data[curr_t] == 0x0E and curr_t + 7 <= len(sec_data):
                                    arg_len = u16_field.unpack(sec_data, curr_t + 5, endian)[0]
                                    curr_t += 7 + arg_len
                                    continue
                                curr_t += 1
                            t_str = sec_data[off:curr_t].decode(encoding, errors="replace")
                        texts.append(t_str)
                    else:
                        texts.append("")

            else:
                other_sections.append((sec_magic, sec_data))

            # 16-byte alignment
            pad = (16 - (sec_size % 16)) % 16
            pos += MSBTSectionHeaderStruct.sizeof() + sec_size + pad

        # Map labels to text entries without dropping unlabelled strings
        idx_to_label: Dict[int, str] = {}
        for l_name, idx in labels:
            idx_to_label[idx] = l_name

        entries: List[MSBTEntry] = []
        for i, t_val in enumerate(texts):
            l_name = idx_to_label.get(i, f"STR_{i}")
            attr = attributes[i] if i < len(attributes) else b""
            entries.append(MSBTEntry(label=l_name, text=t_val, attributes=attr))

        return cls(
            entries=entries,
            encoding=encoding,
            endian=endian,
            attribute_size=attribute_size,
            other_sections=other_sections,
        )

    def to_bytes(self, endian: Optional[str] = None) -> bytes:
        """Serializes MSBTFile back into Nintendo MSBT binary container."""
        endian = endian or self.endian
        bom = b"\xFE\xFF" if endian == ">" else b"\xFF\xFE"
        enc_code = 0 if self.encoding == "utf-8" else 1
        codec = "utf-8" if enc_code == 0 else ("utf-16-be" if endian == ">" else "utf-16-le")

        # 1. Build LBL1 Section (Single hash bucket group)
        lbl_body = BinaryWriter(endian=endian)
        lbl_body.write_u32(1)  # 1 group
        # Group 0: count, offset (relative to table start)
        lbl_body.write_u32(len(self.entries))
        lbl_body.write_u32(12)

        for i, e in enumerate(self.entries):
            l_bytes = e.label.encode("ascii", errors="replace")
            lbl_body.write_u8(len(l_bytes))
            lbl_body.write_bytes(l_bytes)
            lbl_body.write_u32(i)

        lbl_body_bytes = lbl_body.to_bytes()
        lbl_size = len(lbl_body_bytes)

        lbl_sec = BinaryWriter(endian=endian)
        lbl_sec.write_bytes(
            MSBTSectionHeaderStruct(magic=b"LBL1", size=lbl_size).to_bytes(endian=endian)
        )
        lbl_sec.write_bytes(lbl_body_bytes)
        lbl_sec.align(16)
        lbl_sec_bytes = lbl_sec.to_bytes()

        # 2. Build ATR1 Section (if attributes are present)
        has_attrs = self.attribute_size > 0 or any(e.attributes for e in self.entries)
        atr_sec_bytes = b""
        if has_attrs:
            eff_attr_size = self.attribute_size or max((len(e.attributes) for e in self.entries), default=0)
            atr_body = BinaryWriter(endian=endian)
            atr_body.write_u32(len(self.entries))
            atr_body.write_u32(eff_attr_size)
            for e in self.entries:
                atr_body.write_bytes(e.attributes.ljust(eff_attr_size, b"\x00")[:eff_attr_size])
            atr_body_bytes = atr_body.to_bytes()
            atr_sec = BinaryWriter(endian=endian)
            atr_sec.write_bytes(
                MSBTSectionHeaderStruct(magic=b"ATR1", size=len(atr_body_bytes)).to_bytes(endian=endian)
            )
            atr_sec.write_bytes(atr_body_bytes)
            atr_sec.align(16)
            atr_sec_bytes = atr_sec.to_bytes()

        # 3. Build TXT2 Section
        str_count = len(self.entries)
        txt_body = BinaryWriter(endian=endian)
        txt_body.write_u32(str_count)

        # Offsets placeholder
        table_offset_pos = txt_body.tell()
        txt_body.pad(str_count * 4)

        string_pool = BinaryWriter(endian=endian)
        offsets: List[int] = []
        null_term = b"\x00" if enc_code == 0 else b"\x00\x00"

        for e in self.entries:
            offsets.append(string_pool.tell())
            string_pool.write_bytes(e.text.encode(codec, errors="replace"))
            string_pool.write_bytes(null_term)

        # Write actual offsets relative to start of TXT2 body
        pool_start_offset = 4 + str_count * 4
        with txt_body.at(table_offset_pos):
            for off in offsets:
                txt_body.write_u32(pool_start_offset + off)

        txt_body.write_bytes(string_pool.to_bytes())
        txt_body_bytes = txt_body.to_bytes()
        txt_size = len(txt_body_bytes)

        txt_sec = BinaryWriter(endian=endian)
        txt_sec.write_bytes(
            MSBTSectionHeaderStruct(magic=b"TXT2", size=txt_size).to_bytes(endian=endian)
        )
        txt_sec.write_bytes(txt_body_bytes)
        txt_sec.align(16)
        txt_sec_bytes = txt_sec.to_bytes()

        # 4. Serialize other preserved sections
        other_sec_bytes: List[bytes] = []
        for sec_magic, sec_payload in self.other_sections:
            sec_w = BinaryWriter(endian=endian)
            sec_w.write_bytes(
                MSBTSectionHeaderStruct(magic=sec_magic, size=len(sec_payload)).to_bytes(endian=endian)
            )
            sec_w.write_bytes(sec_payload)
            sec_w.align(16)
            other_sec_bytes.append(sec_w.to_bytes())

        # Assemble all sections
        sections: List[bytes] = [lbl_sec_bytes]
        if atr_sec_bytes:
            sections.append(atr_sec_bytes)
        sections.append(txt_sec_bytes)
        sections.extend(other_sec_bytes)

        total_file_size = MSBTHeaderStruct.sizeof() + sum(len(s) for s in sections)

        # 5. Main Header (32 bytes)
        main_writer = BinaryWriter(endian=endian)
        main_writer.write_bytes(
            MSBTHeaderStruct(
                magic=self.MAGIC,
                bom=bom,
                encoding=enc_code,
                version=3,
                section_count=len(sections),
                file_size=total_file_size,
            ).to_bytes(endian=endian)
        )
        for s in sections:
            main_writer.write_bytes(s)

        return main_writer.to_bytes()
