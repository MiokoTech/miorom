import struct
import pytest
from miorom.core.cstruct import CStructOverlay, CStructInstance, CField


def test_cstruct_basic_parse_and_read():
    c_decl = """
    struct Monster {
        uint16_t id;
        char name[16];
        int16_t hp;
        int16_t max_hp;
        uint8_t attack;
        uint8_t defense;
        uint32_t exp;
    };
    """
    overlay = CStructOverlay.from_c(c_decl, endian="<", pack_alignment=1)
    assert overlay.name == "Monster"
    # id(2) + name(16) + hp(2) + max_hp(2) + attack(1) + defense(1) + exp(4) = 28 bytes
    assert overlay.size == 28
    assert len(overlay.fields) == 7

    # Build binary monster
    raw = bytearray(28)
    struct.pack_into("<H", raw, 0, 101)                # id = 101
    name_bytes = b"Slime King\x00"
    raw[2 : 2 + len(name_bytes)] = name_bytes           # name
    struct.pack_into("<hh", raw, 18, 250, 300)          # hp, max_hp
    struct.pack_into("<BB", raw, 22, 45, 30)            # attack, defense
    struct.pack_into("<I", raw, 24, 1500)               # exp

    monster = overlay.read(bytes(raw))
    assert monster.id == 101
    assert monster.name == "Slime King"
    assert monster.hp == 250
    assert monster.max_hp == 300
    assert monster.attack == 45
    assert monster.defense == 30
    assert monster.exp == 1500

    # Dict access
    assert monster["id"] == 101
    assert monster["name"] == "Slime King"


def test_cstruct_write_and_pack():
    c_decl = """
    struct Item {
        uint8_t item_id;
        uint8_t quantity;
        uint16_t price;
    };
    """
    overlay = CStructOverlay.from_c(c_decl, endian="<", pack_alignment=1)
    assert overlay.size == 4

    packed = overlay.pack({"item_id": 5, "quantity": 99, "price": 450})
    assert len(packed) == 4
    assert packed[0] == 5
    assert packed[1] == 99
    assert struct.unpack_from("<H", packed, 2)[0] == 450

    # Test in-place write
    buf = bytearray(16)
    overlay.write(buf, 8, {"item_id": 10, "quantity": 1, "price": 1000})
    inst = overlay.read(bytes(buf), offset=8)
    assert inst.item_id == 10
    assert inst.quantity == 1
    assert inst.price == 1000


def test_cstruct_read_table():
    c_decl = """
    struct Point {
        int16_t x;
        int16_t y;
    };
    """
    overlay = CStructOverlay.from_c(c_decl, endian="<", pack_alignment=1)
    assert overlay.size == 4

    # Table of 3 points
    raw = struct.pack("<6h", 10, 20, 30, 40, -5, -10)
    pts = overlay.read_table(raw, offset=0, count=3)
    assert len(pts) == 3
    assert pts[0].x == 10 and pts[0].y == 20
    assert pts[1].x == 30 and pts[1].y == 40
    assert pts[2].x == -5 and pts[2].y == -10


def test_cstruct_nested():
    point_c = "struct Point { int16_t x; int16_t y; };"
    point_overlay = CStructOverlay.from_c(point_c, endian="<", pack_alignment=1)

    rect_c = """
    struct Rect {
        Point topleft;
        Point bottomright;
    };
    """
    rect_overlay = CStructOverlay.from_c(
        rect_c,
        endian="<",
        pack_alignment=1,
        known_structs={"point": point_overlay},
    )
    assert rect_overlay.size == 8

    raw = struct.pack("<4h", 0, 0, 100, 200)
    rect = rect_overlay.read(raw)
    assert rect.topleft.x == 0
    assert rect.topleft.y == 0
    assert rect.bottomright.x == 100
    assert rect.bottomright.y == 200
    d = rect.to_dict()
    assert d["topleft"]["x"] == 0
    assert d["bottomright"]["y"] == 200
