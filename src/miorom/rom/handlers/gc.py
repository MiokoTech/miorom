import os
from typing import Any, Dict, Optional

from miorom.core.binary import BinaryReader
from miorom.platforms.gc.disc import GameCubeDisc, GCHeader
from miorom.rom.base import BaseRomHandler
from miorom.security import sanitize_extract_path


def _extract_main_dol(dol_data: bytes, fst_offset: int, dol_offset: int) -> bytes:
    """Helper to extract main.dol with exact size calculation if valid DOL header."""
    from miorom.link.dol import DolBinary

    if len(dol_data) >= 0x100 and DolBinary.is_dol(dol_data):
        try:
            dol = DolBinary(dol_data)
            dol_len = max([sec.end_offset for sec in dol.text_sections + dol.data_sections], default=0x100)
            return dol_data[:dol_len]
        except Exception:
            pass
    if fst_offset > dol_offset:
        return dol_data[: fst_offset - dol_offset]
    return dol_data


class GameCubeRomHandler(BaseRomHandler):
    """
    GameCube / Wii Disc Image (.iso, .gcm) handler.
    Unpacks FST filesystem and repacks into valid GameCube disc image.
    """

    name = "gamecube"
    description = "GameCube / Wii Disc Image"
    extensions = [".iso", ".gcm", ".rvz"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        # Check RVZ / WIA container
        if len(data) >= 4 and data[:4] in (b"RVZ\x01", b"WIA\x01"):
            if len(data) >= 0x48 + 144:
                disc_type = BinaryReader.unpack_u32(data, 0x48, endian=">")
                dhead = data[0x48 + 16 : 0x48 + 16 + 128]
                gc_magic = BinaryReader.unpack_u32(dhead, 0x1C, endian=">")
                if disc_type == 1 or gc_magic == GameCubeDisc.GC_MAGIC:
                    return True
                if disc_type == 2:
                    return False
            return True

        if len(data) >= 0x20:
            magic = BinaryReader.unpack_u32(data, 0x1C, endian=">")
            if magic == GameCubeDisc.GC_MAGIC:
                # If it has Wii magic at 0x18, let WiiRomHandler handle it
                wii_magic = BinaryReader.unpack_u32(data, 0x18, endian=">")
                if wii_magic == 0x5D1C9EA3:
                    return False
                return True

        if filepath and os.path.isfile(filepath):
            try:
                with open(filepath, "rb") as f:
                    hdr = f.read(0x48 + 144)
                    if len(hdr) >= 4 and hdr[:4] in (b"RVZ\x01", b"WIA\x01"):
                        if len(hdr) >= 0x48 + 144:
                            disc_type = BinaryReader.unpack_u32(hdr, 0x48, endian=">")
                            dhead = hdr[0x48 + 16 : 0x48 + 16 + 128]
                            gc_magic = BinaryReader.unpack_u32(dhead, 0x1C, endian=">")
                            if disc_type == 1 or gc_magic == GameCubeDisc.GC_MAGIC:
                                return True
                            if disc_type == 2:
                                return False
                        return True
                    if len(hdr) >= 0x20:
                        wii_magic = BinaryReader.unpack_u32(hdr, 0x18, endian=">")
                        gc_magic = BinaryReader.unpack_u32(hdr, 0x1C, endian=">")
                        if wii_magic == 0x5D1C9EA3:
                            return False
                        return gc_magic == GameCubeDisc.GC_MAGIC
            except OSError:
                return False

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        filepath = kwargs.pop("filepath", None)
        if (filepath and filepath.lower().endswith(".rvz")) or (len(data) >= 4 and data[:4] in (b"RVZ\x01", b"WIA\x01")):
            return self.unpack_rvz(data, filepath, output_dir, **kwargs)

        if filepath and os.path.isfile(filepath):
            return self.unpack_file(filepath, output_dir, **kwargs)

        disc = GameCubeDisc(data)
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Save disc header
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(disc.header.pack())

        # System sectors up to FST
        base_size = min(len(data), disc.header.fst_offset if disc.header.fst_offset > 0 else 0x450000)
        with open(os.path.join(sys_dir, "disc_base.bin"), "wb") as f:
            f.write(data[:base_size])

        # Extract main.dol if present
        if disc.header.dol_offset > 0 and disc.header.dol_offset < len(data):
            main_dol = _extract_main_dol(
                data[disc.header.dol_offset :],
                disc.header.fst_offset,
                disc.header.dol_offset,
            )
            with open(os.path.join(sys_dir, "main.dol"), "wb") as f:
                f.write(main_dol)

        # Extract all files from FST
        extracted_count = 0
        for rel_path, file_data in disc.files.items():
            dest = sanitize_extract_path(root_dir, rel_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(file_data)
            extracted_count += 1

        return {
            "format": self.name,
            "platform": "GameCube / Wii",
            "game_id": disc.header.game_id,
            "maker_code": disc.header.maker_code,
            "game_title": disc.header.game_title,
            "disc_number": disc.header.disc_number,
            "version": disc.header.version,
            "audio_streaming": disc.header.audio_streaming,
            "stream_buf_size": disc.header.stream_buf_size,
            "file_count": extracted_count,
            "dol_offset": f"0x{disc.header.dol_offset:08X}",
            "fst_offset": f"0x{disc.header.fst_offset:08X}",
        }

    def unpack_file(self, filepath: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        """Streaming disc unpack directly from file, consuming minimal RAM."""
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        with open(filepath, "rb") as f_in:
            hdr_bytes = f_in.read(0x440)
            header = GCHeader.parse(hdr_bytes)

            with open(os.path.join(sys_dir, "header.bin"), "wb") as f_out:
                f_out.write(header.pack())

            f_in.seek(0)
            file_size = os.path.getsize(filepath)
            base_size = min(file_size, header.fst_offset if header.fst_offset > 0 else 0x450000)
            with open(os.path.join(sys_dir, "disc_base.bin"), "wb") as f_out:
                rem = base_size
                while rem > 0:
                    chunk = f_in.read(min(rem, 65536))
                    if not chunk:
                        break
                    f_out.write(chunk)
                    rem -= len(chunk)

            # Extract main.dol if present
            if header.dol_offset > 0 and header.dol_offset < file_size:
                f_in.seek(header.dol_offset)
                hdr_100 = f_in.read(0x100)
                from miorom.link.dol import DolBinary
                if len(hdr_100) == 0x100 and DolBinary.is_dol(hdr_100):
                    try:
                        dol = DolBinary(hdr_100)
                        dol_len = max([sec.end_offset for sec in dol.text_sections + dol.data_sections], default=0x100)
                    except Exception:
                        dol_len = (header.fst_offset - header.dol_offset) if header.fst_offset > header.dol_offset else 0x400000
                elif header.fst_offset > header.dol_offset:
                    dol_len = header.fst_offset - header.dol_offset
                else:
                    dol_len = min(file_size - header.dol_offset, 0x800000)

                f_in.seek(header.dol_offset)
                with open(os.path.join(sys_dir, "main.dol"), "wb") as f_dol:
                    rem = dol_len
                    while rem > 0:
                        chunk = f_in.read(min(rem, 65536))
                        if not chunk:
                            break
                        f_dol.write(chunk)
                        rem -= len(chunk)

            f_in.seek(header.fst_offset)
            fst_data = f_in.read(header.fst_size)
            entries = GameCubeDisc.parse_fst_entries(fst_data)

            extracted_count = 0
            for entry in entries:
                if entry.is_directory:
                    continue
                dest = sanitize_extract_path(root_dir, entry.path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                f_in.seek(entry.file_offset)
                with open(dest, "wb") as f_out:
                    rem = entry.file_size
                    while rem > 0:
                        chunk = f_in.read(min(rem, 65536))
                        if not chunk:
                            break
                        f_out.write(chunk)
                        rem -= len(chunk)
                extracted_count += 1

        return {
            "format": self.name,
            "platform": "GameCube / Wii",
            "game_id": header.game_id,
            "maker_code": header.maker_code,
            "game_title": header.game_title,
            "disc_number": header.disc_number,
            "version": header.version,
            "audio_streaming": header.audio_streaming,
            "stream_buf_size": header.stream_buf_size,
            "file_count": extracted_count,
            "dol_offset": f"0x{header.dol_offset:08X}",
            "fst_offset": f"0x{header.fst_offset:08X}",
            "streaming": True,
        }

    def unpack_rvz(self, data: bytes, filepath: Optional[str], output_dir: str, **kwargs) -> Dict[str, Any]:
        """Streaming GameCube disc unpack directly from RVZ container."""
        from miorom.platforms.iso.rvz import RVZDisc

        if filepath and os.path.isfile(filepath):
            rvz = RVZDisc.from_file(filepath)
        else:
            rvz = RVZDisc.from_bytes(data)

        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        hdr_bytes = rvz.read_at(0, 0x440)
        header = GCHeader.parse(hdr_bytes)

        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(header.pack())

        # Save disc base for repacking (CRITICAL FIX!)
        base_size = min(rvz.iso_file_size, header.fst_offset if header.fst_offset > 0 else 0x450000)
        base_data = rvz.read_at(0, base_size)
        with open(os.path.join(sys_dir, "disc_base.bin"), "wb") as f:
            f.write(base_data)

        # Extract main.dol if present
        if header.dol_offset > 0 and header.dol_offset < rvz.iso_file_size:
            max_read = min(0x1000000, rvz.iso_file_size - header.dol_offset)
            dol_slice = rvz.read_at(header.dol_offset, max_read)
            main_dol = _extract_main_dol(dol_slice, header.fst_offset, header.dol_offset)
            with open(os.path.join(sys_dir, "main.dol"), "wb") as f:
                f.write(main_dol)

        fst_data = rvz.read_at(header.fst_offset, header.fst_size)
        entries = GameCubeDisc.parse_fst_entries(fst_data)

        extracted_count = 0
        for entry in entries:
            if entry.is_directory:
                continue
            dest = sanitize_extract_path(root_dir, entry.path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            content = rvz.read_at(entry.file_offset, entry.file_size)
            with open(dest, "wb") as f:
                f.write(content)
            extracted_count += 1

        return {
            "format": self.name,
            "platform": "GameCube",
            "game_id": header.game_id,
            "maker_code": header.maker_code,
            "game_title": header.game_title,
            "disc_number": header.disc_number,
            "version": header.version,
            "file_count": extracted_count,
            "dol_offset": f"0x{header.dol_offset:08X}",
            "fst_offset": f"0x{header.fst_offset:08X}",
            "streaming": True,
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        sys_dir = os.path.join(input_dir, "sys")
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        base_path = os.path.join(sys_dir, "disc_base.bin")
        if os.path.isfile(base_path):
            with open(base_path, "rb") as f:
                base_data = f.read()
            disc = GameCubeDisc(base_data)
        else:
            # Synthesize minimal base
            synth = bytearray(0x450000)
            header_path = os.path.join(sys_dir, "header.bin")
            if os.path.isfile(header_path):
                with open(header_path, "rb") as f:
                    synth[:0x440] = f.read()[:0x440]
            else:
                # Default GC header
                default_hdr = GCHeader(
                    game_id="RE01",
                    maker_code="01",
                    disc_number=0,
                    version=0,
                    audio_streaming=False,
                    stream_buf_size=0,
                    magic=GameCubeDisc.GC_MAGIC,
                    game_title="GameCube Disc",
                    dol_offset=0,
                    fst_offset=0x450000,
                    fst_size=0,
                    fst_max_size=0x100000,
                    user_pos=0x550000,
                    user_length=0,
                )
                synth[:0x440] = default_hdr.pack()
            disc = GameCubeDisc(bytes(synth))

        # Check for modified sys/header.bin
        header_path = os.path.join(sys_dir, "header.bin")
        if os.path.isfile(header_path):
            with open(header_path, "rb") as f:
                hdr_bytes = f.read()
            if len(hdr_bytes) >= 0x440:
                disc.header = GCHeader.parse(hdr_bytes)
                if len(disc.raw_data) >= 0x440:
                    disc.raw_data[:0x440] = hdr_bytes[:0x440]

        # Check for modified sys/main.dol
        dol_path = os.path.join(sys_dir, "main.dol")
        if os.path.isfile(dol_path):
            with open(dol_path, "rb") as f:
                new_dol = f.read()
            if new_dol:
                dol_offset = disc.header.dol_offset
                if dol_offset == 0:
                    dol_offset = 0x10000
                    disc.header.dol_offset = dol_offset
                needed_len = dol_offset + len(new_dol)
                if len(disc.raw_data) < needed_len:
                    disc.raw_data.extend(b"\x00" * (needed_len - len(disc.raw_data)))
                disc.raw_data[dol_offset : dol_offset + len(new_dol)] = new_dol
                if disc.header.fst_offset < dol_offset + len(new_dol):
                    disc.header.fst_offset = (dol_offset + len(new_dol) + 0x7FFF) & ~0x7FFF

        # Clear existing files and load all files from root_dir
        disc.files.clear()
        for root, _, files in os.walk(root_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel = os.path.relpath(full_path, root_dir).replace("\\", "/").strip("/")
                with open(full_path, "rb") as f:
                    disc.files[rel] = f.read()

        alignment = kwargs.get("alignment", 32)
        iso_bytes = disc.to_bytes(alignment=alignment)

        out_fmt = str(kwargs.get("format", "iso")).lower().strip()
        if out_fmt == "rvz":
            from miorom.platforms.iso.rvz import RVZDisc
            from miorom.platforms.wii.disc import DiscStream

            return RVZDisc.create_from_stream(
                disc_stream=DiscStream.from_bytes(iso_bytes),
                total_size=len(iso_bytes),
                disc_type=1,
            )

        return iso_bytes
