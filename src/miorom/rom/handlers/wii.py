"""
miorom.rom.handlers.wii
~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii Optical Disc (.iso, .wii) and WBFS (.wbfs) ROM Handler.
Integrates Wii optical disc unpacking, partition extraction, FST inspection,
and repacking into the unified RomManager and CLI pipeline.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from miorom.core import schema
from miorom.core.binary import BinaryReader
from miorom.platforms.wii.disc import (
    CLUSTER_SIZE,
    PARTITION_TYPE_DATA,
    WBFS_MAGIC,
    WII_COMMON_KEY_RETAIL,
    WII_DISC_MAGIC,
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
)
from miorom.platforms.wii.u8 import (
    WADTicket,
    WADTmd,
    aes128_cbc_encrypt,
)
from miorom.rom.base import BaseRomHandler
from miorom.security import sanitize_extract_path


def _create_default_ticket_and_tmd(
    title_id: bytes = b"\x00\x01\x00\x00RMCE",
    title_key: Optional[bytes] = None,
) -> Tuple[WADTicket, WADTmd, bytes]:
    """Generates a minimal valid Ticket and TMD with encrypted Title Key."""
    resolved_key = title_key or bytes.fromhex("112233445566778899aabbccddeeff00")

    tik_raw = bytearray(0x2A4)
    tik_raw[0x1CB : 0x1D3] = title_id
    iv = title_id + (b"\x00" * 8)
    enc_title_key = aes128_cbc_encrypt(resolved_key, WII_COMMON_KEY_RETAIL, iv)
    tik_raw[0x1F0 : 0x200] = enc_title_key
    ticket = WADTicket.from_bytes(bytes(tik_raw))

    tmd_raw = bytearray(0x1E4 + 36)
    schema.pack_into(">H", tmd_raw, 0x1DE, 1)  # num_contents = 1
    tmd = WADTmd.from_bytes(bytes(tmd_raw))

    return ticket, tmd, resolved_key


class WiiRomHandler(BaseRomHandler):
    """
    Nintendo Wii Optical Disc Image (.iso, .wii) and WBFS Container (.wbfs) handler.
    Unpacks encrypted game partitions, FST filesystems, and system binaries (boot.bin, bi2.bin, apploader.img, main.dol),
    and repacks them into playable disc images with Trucha Bug fake-signing.
    """

    name = "wii"
    description = "Nintendo Wii Optical Disc (.iso, .wbfs, .rvz)"
    extensions = [".iso", ".wbfs", ".rvz"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        """
        Determines if the given data or file is a Nintendo Wii disc (.iso/.wbfs/.rvz).
        """
        # 1. RVZ Container Magic (b"RVZ\x01" or b"WIA\x01" at offset 0x00)
        if len(data) >= 4 and data[:4] in (b"RVZ\x01", b"WIA\x01"):
            if len(data) >= 0x48 + 144:
                disc_type = BinaryReader.unpack_u32(data, 0x48, endian=">")
                dhead = data[0x48 + 16 : 0x48 + 16 + 128]
                wii_magic = BinaryReader.unpack_u32(dhead, 0x18, endian=">")
                if disc_type == 2 or wii_magic == WII_DISC_MAGIC:
                    return True
                if disc_type == 1:
                    return False
            return True

        # 2. WBFS Container Magic (b"WBFS" at offset 0x00)
        if len(data) >= 4 and data[:4] == WBFS_MAGIC:
            return True

        # 3. Wii Disc Magic (0x5D1C9EA3 at offset 0x18)
        if len(data) >= 0x20:
            magic = BinaryReader.unpack_u32(data, 0x18, endian=">")
            if magic == WII_DISC_MAGIC:
                return True

        # 4. Partition table inspection at 0x40000 (for large buffers)
        if len(data) >= 0x40004:
            part_count = BinaryReader.unpack_u32(data, 0x40000, endian=">")
            if 0 < part_count <= 8:
                return True

        # 5. File-based inspection
        if filepath and os.path.isfile(filepath):
            try:
                with open(filepath, "rb") as f:
                    hdr = f.read(0x48 + 144)
                    if len(hdr) >= 4 and hdr[:4] in (b"RVZ\x01", b"WIA\x01"):
                        if len(hdr) >= 0x48 + 144:
                            disc_type = BinaryReader.unpack_u32(hdr, 0x48, endian=">")
                            dhead = hdr[0x48 + 16 : 0x48 + 16 + 128]
                            wii_magic = BinaryReader.unpack_u32(dhead, 0x18, endian=">")
                            if disc_type == 2 or wii_magic == WII_DISC_MAGIC:
                                return True
                            if disc_type == 1:
                                return False
                        return True
                    if len(hdr) >= 4 and hdr[:4] == WBFS_MAGIC:
                        return True
                    if len(hdr) >= 0x20:
                        magic = BinaryReader.unpack_u32(hdr, 0x18, endian=">")
                        if magic == WII_DISC_MAGIC:
                            return True
                    # Check 0x40000 partition table
                    if os.path.getsize(filepath) >= 0x40004:
                        f.seek(0x40000)
                        part_hdr = f.read(4)
                        if len(part_hdr) == 4:
                            part_count = BinaryReader.unpack_u32(part_hdr, 0, endian=">")
                            if 0 < part_count <= 8:
                                return True
            except OSError:
                return False

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        """
        Unpacks a Wii disc image into the destination output directory.
        Extracts system files into sys/ and virtual game assets into root/.
        """
        filepath = kwargs.pop("filepath", None)
        common_key = kwargs.pop("common_key", None)

        if filepath and os.path.isfile(filepath):
            disc = WiiDisc.from_file(filepath, common_key=common_key)
        else:
            disc = WiiDisc.from_bytes(data, common_key=common_key)

        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Save root disc header (0x0000..0x0440)
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(disc.header.pack())

        # Select the main data partition (or fallback to the first partition)
        data_part: Optional[WiiPartition] = None
        for p in disc.partitions:
            if p.is_data_partition:
                data_part = p
                break
        if data_part is None and disc.partitions:
            data_part = disc.partitions[0]

        extracted_count = 0
        if data_part is not None:
            # Save system binaries in sys/
            if data_part.boot_bin:
                with open(os.path.join(sys_dir, "boot.bin"), "wb") as f:
                    f.write(data_part.boot_bin)
            if data_part.bi2_bin:
                with open(os.path.join(sys_dir, "bi2.bin"), "wb") as f:
                    f.write(data_part.bi2_bin)
            if data_part.apploader_bin:
                with open(os.path.join(sys_dir, "apploader.img"), "wb") as f:
                    f.write(data_part.apploader_bin)
            if data_part.main_dol:
                with open(os.path.join(sys_dir, "main.dol"), "wb") as f:
                    f.write(data_part.main_dol)

            # Save Ticket and TMD
            with open(os.path.join(sys_dir, "ticket.bin"), "wb") as f:
                f.write(data_part.ticket.to_bytes())
            with open(os.path.join(sys_dir, "tmd.bin"), "wb") as f:
                f.write(data_part.tmd.to_bytes())

            # Save opening.bnr if present
            for bnr_name in ("opening.bnr", "files/opening.bnr", "sys/opening.bnr"):
                try:
                    bnr_data = data_part[bnr_name]
                    if bnr_data:
                        with open(os.path.join(sys_dir, "opening.bnr"), "wb") as f:
                            f.write(bnr_data)
                        break
                except (KeyError, Exception):
                    pass

            # Extract all FST game assets into root/
            for vpath in data_part.list_files():
                if vpath.startswith("files/"):
                    subpath = vpath[6:].lstrip("/")
                    dest = sanitize_extract_path(root_dir, subpath)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(data_part[vpath])
                    extracted_count += 1

        return {
            "format": self.name,
            "platform": "Nintendo Wii",
            "game_id": disc.header.game_id,
            "maker_code": disc.header.maker_code,
            "game_title": disc.header.game_title,
            "disc_number": disc.header.disc_number,
            "version": disc.header.version,
            "partitions_count": len(disc.partitions),
            "file_count": extracted_count,
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        """
        Reads unpacked directory and rebuilds a playable Nintendo Wii optical disc (.iso or .wbfs).
        Automatically applies Trucha Bug fake-signing and recomputes all hash trees.
        """
        sys_dir = os.path.join(input_dir, "sys")
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "files")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        # 1. Parse or create Disc Header
        header_path = os.path.join(sys_dir, "header.bin")
        if os.path.isfile(header_path):
            with open(header_path, "rb") as f:
                header = WiiDiscHeader.parse(f.read())
        else:
            header = WiiDiscHeader(
                game_id="RMCE",
                maker_code="01",
                disc_number=0,
                version=1,
                audio_streaming=False,
                stream_buf_size=0,
                magic=WII_DISC_MAGIC,
                gc_magic=0xC2339F3D,
                game_title="Nintendo Wii Game",
            )

        # 2. Read System binaries from sys/
        def _read_opt(name: str) -> bytes:
            path = os.path.join(sys_dir, name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return f.read()
            return b""

        boot_bin = _read_opt("boot.bin")
        bi2_bin = _read_opt("bi2.bin")
        apploader_bin = _read_opt("apploader.img")
        main_dol = _read_opt("main.dol")
        bnr_raw = _read_opt("opening.bnr")

        # 3. Read or create Ticket & TMD
        ticket_raw = _read_opt("ticket.bin")
        tmd_raw = _read_opt("tmd.bin")
        common_key = kwargs.get("common_key") or WII_COMMON_KEY_RETAIL

        if ticket_raw and tmd_raw:
            ticket = WADTicket.from_bytes(ticket_raw)
            tmd = WADTmd.from_bytes(tmd_raw)
            try:
                title_key = ticket.decrypt_title_key(common_key)
            except Exception:
                title_key = bytes.fromhex("112233445566778899aabbccddeeff00")
        else:
            clean_gid = header.game_id.encode("ascii", errors="replace")[:4].ljust(4, b"\x00")
            ticket, tmd, title_key = _create_default_ticket_and_tmd(
                title_id=b"\x00\x01\x00\x00" + clean_gid
            )

        # 4. Construct Partition
        part = WiiPartition(
            partition_offset=0x50000,
            partition_type=PARTITION_TYPE_DATA,
            ticket=ticket,
            tmd=tmd,
            title_key=title_key,
            data_offset=0x58000,
            data_size=CLUSTER_SIZE * 2,
            h3_offset=0x51000,
            boot_bin=boot_bin,
            bi2_bin=bi2_bin,
            apploader_bin=apploader_bin,
            main_dol=main_dol,
        )

        # 5. Populate files from root_dir into FST
        if os.path.isdir(root_dir):
            for root, _, files in os.walk(root_dir):
                for fname in files:
                    full_path = os.path.join(root, fname)
                    rel = os.path.relpath(full_path, root_dir).replace("\\", "/").strip("/")
                    with open(full_path, "rb") as f:
                        part["files/" + rel] = f.read()

        # Ensure opening.bnr from sys/ is staged in memory if omitted in root_dir
        if bnr_raw and "files/opening.bnr" not in part and "opening.bnr" not in part:
            part["files/opening.bnr"] = bnr_raw

        disc = WiiDisc(header=header, partitions=[part])
        out_format = str(kwargs.get("format", "iso")).lower().strip()

        fake_sign = kwargs.get("fake_sign", True)
        if out_format == "rvz":
            return disc.to_rvz(fake_sign=fake_sign)
        if out_format == "wbfs":
            return disc.to_wbfs(fake_sign=fake_sign)
        return disc.to_bytes(fake_sign=fake_sign)
