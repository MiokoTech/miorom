import pytest
from miorom.graphics.oam import HardwareOamCodec, SpriteDescriptor


def test_nes_oam_roundtrip():
    sprites = [
        SpriteDescriptor(x=100, y=50, tile_id=12, palette=2, flip_h=True, flip_v=False, priority=1),
        SpriteDescriptor(x=200, y=150, tile_id=64, palette=0, flip_h=False, flip_v=True, priority=0),
    ]

    encoded = HardwareOamCodec.encode_nes(sprites)
    assert len(encoded) == 8

    decoded = HardwareOamCodec.decode_nes(encoded)
    assert len(decoded) == 2

    assert decoded[0].x == 100
    assert decoded[0].y == 50
    assert decoded[0].tile_id == 12
    assert decoded[0].palette == 2
    assert decoded[0].flip_h is True
    assert decoded[0].flip_v is False
    assert decoded[0].priority == 1

    assert decoded[1].x == 200
    assert decoded[1].y == 150
    assert decoded[1].tile_id == 64
    assert decoded[1].flip_v is True


def test_gb_oam_roundtrip():
    sprites = [
        SpriteDescriptor(x=16, y=32, tile_id=5, palette=1, flip_h=True, flip_v=False, priority=0, vram_bank=1),
    ]

    encoded = HardwareOamCodec.encode_gb(sprites)
    assert len(encoded) == 4

    decoded = HardwareOamCodec.decode_gb(encoded)
    assert len(decoded) == 1
    assert decoded[0].x == 16
    assert decoded[0].y == 32
    assert decoded[0].tile_id == 5
    assert decoded[0].flip_h is True
    assert decoded[0].vram_bank == 1


def test_snes_oam_roundtrip():
    sprites = [
        SpriteDescriptor(x=120, y=80, tile_id=0x120, palette=4, flip_h=True, flip_v=True, priority=2, size_flag=1),
        SpriteDescriptor(x=-20, y=100, tile_id=0x50, palette=1, flip_h=False, flip_v=False, priority=0, size_flag=0),
    ]

    t1, t2 = HardwareOamCodec.encode_snes(sprites)
    assert len(t1) == 8
    assert len(t2) == 32

    decoded = HardwareOamCodec.decode_snes(t1, t2)
    assert len(decoded) == 2

    assert decoded[0].x == 120
    assert decoded[0].y == 80
    assert decoded[0].tile_id == 0x120
    assert decoded[0].palette == 4
    assert decoded[0].flip_h is True
    assert decoded[0].flip_v is True
    assert decoded[0].priority == 2
    assert decoded[0].size_flag == 1

    assert decoded[1].x == -20
    assert decoded[1].y == 100
    assert decoded[1].tile_id == 0x50
    assert decoded[1].size_flag == 0


def test_genesis_sat_roundtrip():
    sprites = [
        SpriteDescriptor(x=80, y=60, tile_id=250, palette=2, flip_h=False, flip_v=True, priority=1, width_tiles=2, height_tiles=3, link=1),
        SpriteDescriptor(x=120, y=100, tile_id=10, palette=0, flip_h=True, flip_v=False, priority=0, width_tiles=1, height_tiles=1, link=0),
    ]

    encoded = HardwareOamCodec.encode_genesis(sprites)
    assert len(encoded) == 16

    decoded = HardwareOamCodec.decode_genesis(encoded)
    assert len(decoded) == 2

    assert decoded[0].x == 80
    assert decoded[0].y == 60
    assert decoded[0].tile_id == 250
    assert decoded[0].palette == 2
    assert decoded[0].flip_v is True
    assert decoded[0].priority == 1
    assert decoded[0].width_tiles == 2
    assert decoded[0].height_tiles == 3
    assert decoded[0].link == 1

    assert decoded[1].x == 120
    assert decoded[1].y == 100
    assert decoded[1].link == 0


def test_gba_oam_roundtrip():
    sprites = [
        SpriteDescriptor(x=50, y=40, tile_id=100, palette=8, flip_h=True, flip_v=False, priority=1, size_flag=2, extra_flags=1),
    ]

    encoded = HardwareOamCodec.encode_gba(sprites)
    assert len(encoded) == 8

    decoded = HardwareOamCodec.decode_gba(encoded)
    assert len(decoded) == 1

    assert decoded[0].x == 50
    assert decoded[0].y == 40
    assert decoded[0].tile_id == 100
    assert decoded[0].palette == 8
    assert decoded[0].flip_h is True
    assert decoded[0].flip_v is False
    assert decoded[0].priority == 1
    assert decoded[0].size_flag == 2
    assert decoded[0].extra_flags == 1
