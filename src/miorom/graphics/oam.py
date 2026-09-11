"""
miorom.graphics.oam
~~~~~~~~~~~~~~~~~~~
Hardware Object Attribute Memory (OAM) and sprite descriptor codec for retro consoles.
Parses, manipulates, and serializes low-level sprite attributes across NES, Game Boy/GBC,
SNES (Table 1 + Hi-OAM Table 2), Sega Genesis (Sprite Attribute Table), and GBA.
"""

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miorom.result import MioRomResult


@dataclass
class SpriteDescriptor(MioRomResult):
    """Normalized representation of a single 2D hardware sprite object."""
    x: int
    y: int
    tile_id: int
    palette: int = 0
    flip_h: bool = False
    flip_v: bool = False
    priority: int = 0
    width_tiles: int = 1
    height_tiles: int = 1
    size_flag: int = 0
    vram_bank: int = 0
    extra_flags: int = 0
    link: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class HardwareOamCodec:
    """
    Codec for encoding and decoding binary sprite attribute memory across retro platforms.
    """

    @classmethod
    def decode_nes(cls, data: bytes) -> List[SpriteDescriptor]:
        """Decodes standard 4-byte NES/Famicom OAM entries (up to 64 sprites = 256 bytes)."""
        sprites: List[SpriteDescriptor] = []
        count = len(data) // 4
        for i in range(count):
            offset = i * 4
            y, tile, attr, x = struct.unpack_from("<BBBB", data, offset)
            palette = attr & 0x03
            priority = (attr >> 5) & 0x01
            flip_h = bool((attr >> 6) & 0x01)
            flip_v = bool((attr >> 7) & 0x01)
            sprites.append(
                SpriteDescriptor(
                    x=x,
                    y=y,
                    tile_id=tile,
                    palette=palette,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    priority=priority,
                )
            )
        return sprites

    @classmethod
    def encode_nes(cls, sprites: Sequence[SpriteDescriptor]) -> bytes:
        """Encodes sprite descriptors into NES/Famicom 4-byte OAM binary bytes."""
        out = bytearray()
        for s in sprites:
            attr = s.palette & 0x03
            if s.priority:
                attr |= 1 << 5
            if s.flip_h:
                attr |= 1 << 6
            if s.flip_v:
                attr |= 1 << 7
            out.extend(struct.pack("<BBBB", s.y & 0xFF, s.tile_id & 0xFF, attr, s.x & 0xFF))
        return bytes(out)

    @classmethod
    def decode_gb(cls, data: bytes) -> List[SpriteDescriptor]:
        """Decodes standard 4-byte Game Boy / GBC OAM entries (up to 40 sprites = 160 bytes)."""
        sprites: List[SpriteDescriptor] = []
        count = len(data) // 4
        for i in range(count):
            offset = i * 4
            raw_y, raw_x, tile, flags = struct.unpack_from("<BBBB", data, offset)
            x = raw_x - 8
            y = raw_y - 16
            cgb_pal = flags & 0x07
            bank = (flags >> 3) & 0x01
            dmg_pal = (flags >> 4) & 0x01
            flip_h = bool((flags >> 5) & 0x01)
            flip_v = bool((flags >> 6) & 0x01)
            priority = (flags >> 7) & 0x01
            sprites.append(
                SpriteDescriptor(
                    x=x,
                    y=y,
                    tile_id=tile,
                    palette=cgb_pal if bank or cgb_pal else dmg_pal,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    priority=priority,
                    vram_bank=bank,
                    extra_flags=flags,
                )
            )
        return sprites

    @classmethod
    def encode_gb(cls, sprites: Sequence[SpriteDescriptor]) -> bytes:
        """Encodes sprite descriptors into Game Boy / GBC 4-byte OAM binary bytes."""
        out = bytearray()
        for s in sprites:
            raw_y = (s.y + 16) & 0xFF
            raw_x = (s.x + 8) & 0xFF
            flags = s.palette & 0x07
            if s.vram_bank:
                flags |= 1 << 3
            if s.flip_h:
                flags |= 1 << 5
            if s.flip_v:
                flags |= 1 << 6
            if s.priority:
                flags |= 1 << 7
            out.extend(struct.pack("<BBBB", raw_y, raw_x, s.tile_id & 0xFF, flags))
        return bytes(out)

    @classmethod
    def decode_snes(cls, table1: bytes, table2: bytes) -> List[SpriteDescriptor]:
        """
        Decodes SNES split OAM tables: Table 1 (512 bytes, 4 bytes/sprite) and Table 2 (32 bytes, 2 bits/sprite).
        Supports up to 128 hardware sprites.
        """
        sprites: List[SpriteDescriptor] = []
        count = min(128, len(table1) // 4)

        for i in range(count):
            t1_off = i * 4
            x_low, y, tile_low, attr = struct.unpack_from("<BBBB", table1, t1_off)

            tile_bit8 = attr & 0x01
            palette = (attr >> 1) & 0x07
            priority = (attr >> 4) & 0x03
            flip_h = bool((attr >> 6) & 0x01)
            flip_v = bool((attr >> 7) & 0x01)
            full_tile = tile_low | (tile_bit8 << 8)

            t2_byte_idx = i // 4
            t2_bit_shift = (i % 4) * 2
            x_high = 0
            size_bit = 0
            if t2_byte_idx < len(table2):
                t2_val = table2[t2_byte_idx]
                x_high = (t2_val >> t2_bit_shift) & 0x01
                size_bit = (t2_val >> (t2_bit_shift + 1)) & 0x01

            full_x = x_low | (x_high << 8)
            if full_x >= 256:
                full_x -= 512

            sprites.append(
                SpriteDescriptor(
                    x=full_x,
                    y=y,
                    tile_id=full_tile,
                    palette=palette,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    priority=priority,
                    size_flag=size_bit,
                )
            )

        return sprites

    @classmethod
    def encode_snes(cls, sprites: Sequence[SpriteDescriptor]) -> Tuple[bytes, bytes]:
        """Encodes sprite descriptors into SNES split tables (Table 1 and Hi-OAM Table 2)."""
        table1 = bytearray()
        table2 = bytearray(32)

        for i, s in enumerate(sprites[:128]):
            x_unsigned = s.x if s.x >= 0 else s.x + 512
            x_low = x_unsigned & 0xFF
            x_high = (x_unsigned >> 8) & 0x01

            tile_low = s.tile_id & 0xFF
            tile_bit8 = (s.tile_id >> 8) & 0x01

            attr = tile_bit8
            attr |= (s.palette & 0x07) << 1
            attr |= (s.priority & 0x03) << 4
            if s.flip_h:
                attr |= 1 << 6
            if s.flip_v:
                attr |= 1 << 7

            table1.extend(struct.pack("<BBBB", x_low, s.y & 0xFF, tile_low, attr))

            t2_byte_idx = i // 4
            t2_bit_shift = (i % 4) * 2
            val = (x_high & 0x01) | ((s.size_flag & 0x01) << 1)
            table2[t2_byte_idx] |= (val << t2_bit_shift)

        return bytes(table1), bytes(table2)

    @classmethod
    def decode_genesis(cls, data: bytes) -> List[SpriteDescriptor]:
        """Decodes standard 8-byte Sega Genesis / Mega Drive Sprite Attribute Table (SAT)."""
        sprites: List[SpriteDescriptor] = []
        count = len(data) // 8
        for i in range(count):
            offset = i * 8
            y_raw, dim, link, attr, x_raw = struct.unpack_from(">HBBHH", data, offset)
            y = (y_raw & 0x03FF) - 128
            x = (x_raw & 0x03FF) - 128

            height_tiles = (dim & 0x03) + 1
            width_tiles = ((dim >> 2) & 0x03) + 1

            tile_id = attr & 0x07FF
            flip_h = bool((attr >> 11) & 0x01)
            flip_v = bool((attr >> 12) & 0x01)
            palette = (attr >> 13) & 0x03
            priority = (attr >> 15) & 0x01

            sprites.append(
                SpriteDescriptor(
                    x=x,
                    y=y,
                    tile_id=tile_id,
                    palette=palette,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    priority=priority,
                    width_tiles=width_tiles,
                    height_tiles=height_tiles,
                    link=link,
                )
            )
        return sprites

    @classmethod
    def encode_genesis(cls, sprites: Sequence[SpriteDescriptor]) -> bytes:
        """Encodes sprite descriptors into Sega Genesis / Mega Drive 8-byte SAT binary bytes."""
        out = bytearray()
        for s in sprites:
            y_raw = (s.y + 128) & 0x03FF
            x_raw = (s.x + 128) & 0x03FF

            v_dim = max(0, min(3, s.height_tiles - 1))
            h_dim = max(0, min(3, s.width_tiles - 1))
            dim = v_dim | (h_dim << 2)

            attr = s.tile_id & 0x07FF
            if s.flip_h:
                attr |= 1 << 11
            if s.flip_v:
                attr |= 1 << 12
            attr |= (s.palette & 0x03) << 13
            if s.priority:
                attr |= 1 << 15

            out.extend(struct.pack(">HBBHH", y_raw, dim, s.link & 0xFF, attr, x_raw))
        return bytes(out)

    @classmethod
    def decode_gba(cls, data: bytes) -> List[SpriteDescriptor]:
        """Decodes standard 8-byte GBA OAM entries (up to 128 sprites = 1024 bytes)."""
        sprites: List[SpriteDescriptor] = []
        count = len(data) // 8
        for i in range(count):
            offset = i * 8
            attr0, attr1, attr2, _ = struct.unpack_from("<HHHH", data, offset)
            y = attr0 & 0xFF
            shape = (attr0 >> 14) & 0x03

            x = attr1 & 0x01FF
            if x >= 256:
                x -= 512
            flip_h = bool((attr1 >> 12) & 0x01)
            flip_v = bool((attr1 >> 13) & 0x01)
            size = (attr1 >> 14) & 0x03

            tile_id = attr2 & 0x03FF
            priority = (attr2 >> 10) & 0x03
            palette = (attr2 >> 12) & 0x0F

            sprites.append(
                SpriteDescriptor(
                    x=x,
                    y=y,
                    tile_id=tile_id,
                    palette=palette,
                    flip_h=flip_h,
                    flip_v=flip_v,
                    priority=priority,
                    size_flag=size,
                    extra_flags=shape,
                )
            )
        return sprites

    @classmethod
    def encode_gba(cls, sprites: Sequence[SpriteDescriptor]) -> bytes:
        """Encodes sprite descriptors into standard 8-byte GBA OAM binary bytes."""
        out = bytearray()
        for s in sprites:
            attr0 = s.y & 0xFF
            attr0 |= (s.extra_flags & 0x03) << 14

            x_unsigned = s.x if s.x >= 0 else s.x + 512
            attr1 = x_unsigned & 0x01FF
            if s.flip_h:
                attr1 |= 1 << 12
            if s.flip_v:
                attr1 |= 1 << 13
            attr1 |= (s.size_flag & 0x03) << 14

            attr2 = s.tile_id & 0x03FF
            attr2 |= (s.priority & 0x03) << 10
            attr2 |= (s.palette & 0x0F) << 12

            out.extend(struct.pack("<HHHH", attr0, attr1, attr2, 0))
        return bytes(out)
