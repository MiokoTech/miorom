"""
miorom.graphics.fast3d
~~~~~~~~~~~~~~~~~~~~~~
Nintendo 64 Fast3D / F3DEX / F3DEX2 Display List Texture Parser.
Parses graphics microcode commands (G_SETTIMG, G_SETTILE, G_LOADBLOCK,
G_LOADTILE, G_SETTILESIZE) to extract texture metadata, dimensions, formats,
and memory pointers directly from display list binaries without guesswork.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from miorom.graphics.n64_texture import N64TextureDecoder, N64TextureFormat
from miorom.result import MioRomResult


# Fast3D Image Formats & Sizes
F3D_FMT_NAMES = {0: "rgba", 1: "yuv", 2: "ci", 3: "ia", 4: "i"}
F3D_SIZ_NAMES = {0: 4, 1: 8, 2: 16, 3: 32}


@dataclass
class F3DTextureDescriptor(MioRomResult):
    """Metadata describing a texture extracted from a Fast3D display list."""
    pc: int
    format_name: str         # "rgba16", "rgba32", "ia16", "i8", etc.
    fmt_id: int              # 0=RGBA, 2=CI, 3=IA, 4=I
    siz_id: int              # 0=4b, 1=8b, 2=16b, 3=32b
    width: int
    height: int
    image_ptr: int           # Segmented or physical memory pointer
    tile_index: int = 0
    line_stride: int = 0


class Fast3DParser:
    """
    Parses N64 Fast3D display list microcode binary streams to discover
    and reconstruct loaded textures.
    """

    # Fast3D / F3DEX / F3DEX2 Opcode constants
    G_SETTILE = 0xF5
    G_LOADTILE = 0xF4
    G_LOADBLOCK = 0xF3
    G_SETTILESIZE = 0xF2
    G_SETTIMG = 0xFD
    G_ENDDL = 0xDF

    @classmethod
    def find_textures(
        cls,
        data: bytes,
        base_address: int = 0,
        endian: str = ">",
    ) -> List[F3DTextureDescriptor]:
        """
        Scans a display list stream and reconstructs all textured draw setups.
        """
        textures: List[F3DTextureDescriptor] = []
        fmt = f"{endian}II"
        curr_timg: Optional[Tuple[int, int, int, int]] = None  # (pc, fmt, siz, ptr)
        curr_tile: Optional[Tuple[int, int, int, int]] = None  # (fmt, siz, tile, line)

        for i in range(0, len(data) - 7, 8):
            w0, w1 = struct.unpack_from(fmt, data, i)
            cmd = (w0 >> 24) & 0xFF
            pc = base_address + i

            if cmd == cls.G_SETTIMG:
                # w0: [cmd 8b][fmt 3b][siz 2b][reserved 21b]
                # w1: image pointer
                img_fmt = (w0 >> 21) & 0x07
                img_siz = (w0 >> 19) & 0x03
                img_ptr = w1
                curr_timg = (pc, img_fmt, img_siz, img_ptr)

            elif cmd == cls.G_SETTILE:
                # w0: [cmd 8b][fmt 3b][siz 2b][pad 1b][line 9b][tmem 9b]
                # w1: [pad 5b][tile 3b][palette 4b][clamp/wrap flags...]
                t_fmt = (w0 >> 21) & 0x07
                t_siz = (w0 >> 19) & 0x03
                t_line = (w0 >> 9) & 0x1FF
                tile_idx = (w1 >> 24) & 0x07
                curr_tile = (t_fmt, t_siz, tile_idx, t_line)

            elif cmd in (cls.G_SETTILESIZE, cls.G_LOADTILE):
                # w1: [uls 12b][ult 12b]
                # w2: [lrs 12b][lrt 12b] in 10.2 fixed point
                tile_idx = (w1 >> 24) & 0x07
                uls = (w0 >> 12) & 0x0FFF
                ult = w0 & 0x0FFF
                lrs = (w1 >> 12) & 0x0FFF
                lrt = w1 & 0x0FFF

                # 10.2 fixed-point -> integer dimensions
                width = ((lrs - uls) >> 2) + 1
                height = ((lrt - ult) >> 2) + 1

                if curr_timg and width > 0 and height > 0:
                    timg_pc, t_fmt, t_siz, t_ptr = curr_timg
                    fmt_prefix = F3D_FMT_NAMES.get(t_fmt, "rgba")
                    siz_bits = F3D_SIZ_NAMES.get(t_siz, 16)
                    format_name = f"{fmt_prefix}{siz_bits}"

                    textures.append(F3DTextureDescriptor(
                        pc=timg_pc,
                        format_name=format_name,
                        fmt_id=t_fmt,
                        siz_id=t_siz,
                        width=width,
                        height=height,
                        image_ptr=t_ptr,
                        tile_index=tile_idx,
                    ))

            elif cmd == cls.G_LOADBLOCK:
                # LoadBlock w1: [uls 12b][ult 12b][tile 3b][texels 12b]
                texels = (w1 & 0x0FFF) + 1
                if curr_timg:
                    timg_pc, t_fmt, t_siz, t_ptr = curr_timg
                    fmt_prefix = F3D_FMT_NAMES.get(t_fmt, "rgba")
                    siz_bits = F3D_SIZ_NAMES.get(t_siz, 16)
                    format_name = f"{fmt_prefix}{siz_bits}"

                    # Estimate standard square width if not followed by settilesize
                    width = 32
                    height = texels // 32 if texels >= 32 else 32
                    textures.append(F3DTextureDescriptor(
                        pc=timg_pc,
                        format_name=format_name,
                        fmt_id=t_fmt,
                        siz_id=t_siz,
                        width=width,
                        height=height,
                        image_ptr=t_ptr,
                    ))

        return textures


class Fast3DBuilder:
    """
    Fluent microcode command emitter for constructing N64 Fast3D / F3DEX2 display lists.
    Emits standard 64-bit microcode commands directly in pure Python.
    """

    def __init__(self, endian: str = ">"):
        self.endian = endian
        self.commands: List[Tuple[int, int]] = []

    def set_timg(self, fmt: int, siz: int, image_ptr: int) -> "Fast3DBuilder":
        """Emits G_SETTIMG: Set texture image source pointer."""
        w0 = (0xFD << 24) | ((fmt & 0x07) << 21) | ((siz & 0x03) << 19)
        w1 = image_ptr & 0xFFFFFFFF
        self.commands.append((w0, w1))
        return self

    def set_tile(
        self,
        fmt: int,
        siz: int,
        line: int,
        tmem: int,
        tile: int = 0,
        palette: int = 0,
        clamp_s: int = 0,
        clamp_t: int = 0,
        mask_s: int = 0,
        mask_t: int = 0,
        shift_s: int = 0,
        shift_t: int = 0,
    ) -> "Fast3DBuilder":
        """Emits G_SETTILE: Configure texture tile descriptor."""
        w0 = (
            (0xF5 << 24)
            | ((fmt & 0x07) << 21)
            | ((siz & 0x03) << 19)
            | ((line & 0x1FF) << 9)
            | (tmem & 0x1FF)
        )
        w1 = (
            ((tile & 0x07) << 24)
            | ((palette & 0x0F) << 20)
            | ((clamp_t & 0x01) << 19)
            | ((mask_t & 0x0F) << 14)
            | ((shift_t & 0x0F) << 10)
            | ((clamp_s & 0x01) << 9)
            | ((mask_s & 0x0F) << 4)
            | (shift_s & 0x0F)
        )
        self.commands.append((w0, w1))
        return self

    def set_tile_size(
        self,
        tile: int,
        uls: int,
        ult: int,
        lrs: int,
        lrt: int,
    ) -> "Fast3DBuilder":
        """Emits G_SETTILESIZE: Configure tile dimension bounding coordinates (10.2 fixed point)."""
        w0 = (0xF2 << 24) | (((uls << 2) & 0x0FFF) << 12) | ((ult << 2) & 0x0FFF)
        w1 = ((tile & 0x07) << 24) | (((lrs << 2) & 0x0FFF) << 12) | ((lrt << 2) & 0x0FFF)
        self.commands.append((w0, w1))
        return self

    def load_block(
        self,
        tile: int,
        uls: int,
        ult: int,
        texels: int,
        dxt: int = 0,
    ) -> "Fast3DBuilder":
        """Emits G_LOADBLOCK: Load contiguous texture block into TMEM."""
        w0 = (0xF3 << 24) | ((uls & 0x0FFF) << 12) | (ult & 0x0FFF)
        w1 = ((tile & 0x07) << 24) | (((texels - 1) & 0x0FFF) << 12) | (dxt & 0x0FFF)
        self.commands.append((w0, w1))
        return self

    def end_dl(self) -> "Fast3DBuilder":
        """Emits G_ENDDL: End display list execution."""
        self.commands.append((0xDF000000, 0x00000000))
        return self

    def emit(self) -> bytes:
        """Assembles display list commands into binary bytes."""
        out = bytearray()
        fmt = f"{self.endian}II"
        for w0, w1 in self.commands:
            out.extend(struct.pack(fmt, w0, w1))
        return bytes(out)
