import os
import struct
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.platforms.gc.disc import GameCubeDisc, GCHeader


class GameCubeRomHandler(BaseRomHandler):
    """
    Nintendo GameCube and Wii Disc Image (.iso / .gcm) unpacker and repacker.
    Extracts disc header, system files, and full FST directory tree.
    Repacks modified files into bit-aligned disc images with updated FST tables.
    """

    name = "gamecube"
    description = "GameCube / Wii Disc Image"
    extensions = [".iso", ".gcm"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if len(data) >= 0x20:
            magic = struct.unpack_from(">I", data, 0x1C)[0]
            if magic == GameCubeDisc.GC_MAGIC:
                return True

        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions and len(data) >= 0x440:
                magic = struct.unpack_from(">I", data, 0x1C)[0]
                return magic == GameCubeDisc.GC_MAGIC

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        disc = GameCubeDisc(data)
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Save disc header
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(disc.header.pack())

        # Save disc base system sectors (header, bi2, apploader, boot.dol) up to FST
        base_size = min(len(data), disc.header.fst_offset if disc.header.fst_offset > 0 else 0x450000)
        with open(os.path.join(sys_dir, "disc_base.bin"), "wb") as f:
            f.write(data[:base_size])

        # Extract all files from FST
        extracted_count = 0
        for rel_path, file_data in disc.files.items():
            dest = os.path.join(root_dir, rel_path)
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

        # Clear existing files and load all files from root_dir
        disc.files.clear()
        for root, _, files in os.walk(root_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel = os.path.relpath(full_path, root_dir).replace("\\", "/").strip("/")
                with open(full_path, "rb") as f:
                    disc.files[rel] = f.read()

        alignment = kwargs.get("alignment", 32)
        return disc.to_bytes(alignment=alignment)
