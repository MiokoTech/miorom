import pytest
from miorom.core.bits import (
    rol,
    ror,
    bit_reverse,
    bit_reverse8,
    bit_reverse16,
    bit_reverse32,
    swap_nibbles,
    pack_nibbles,
    unpack_nibbles,
    sign_extend,
    popcount,
    clz,
    ctz,
    bswap16,
    bswap32,
    bswap64,
)


def test_rotations():
    # 8-bit rotation
    val = 0b10000001
    assert rol(val, 1, 8) == 0b00000011
    assert ror(val, 1, 8) == 0b11000000
    assert rol(val, 8, 8) == val
    assert rol(val, 9, 8) == rol(val, 1, 8)

    # 16-bit rotation
    assert rol(0x8001, 1, 16) == 0x0003
    assert ror(0x0003, 1, 16) == 0x8001


def test_bit_reversal():
    assert bit_reverse8(0b10110000) == 0b00001101
    assert bit_reverse8(0x00) == 0x00
    assert bit_reverse8(0xFF) == 0xFF

    assert bit_reverse16(0x8000) == 0x0001
    assert bit_reverse32(0x80000000) == 0x00000001
    assert bit_reverse(0b101, 3) == 0b101
    assert bit_reverse(0b100, 3) == 0b001


def test_nibbles():
    assert swap_nibbles(0x12) == 0x21
    assert swap_nibbles(0xAB) == 0xBA

    assert pack_nibbles(0xA, 0xB) == 0xAB
    assert unpack_nibbles(0xAB) == (0xA, 0xB)


def test_sign_extend():
    # 8-bit: 0xFF is -1, 0x7F is 127, 0x80 is -128
    assert sign_extend(0xFF, 8) == -1
    assert sign_extend(0x7F, 8) == 127
    assert sign_extend(0x80, 8) == -128

    # 12-bit (common in ARM immediate/offset):
    assert sign_extend(0xFFF, 12) == -1
    assert sign_extend(0x800, 12) == -2048
    assert sign_extend(0x7FF, 12) == 2047


def test_bit_counting():
    assert popcount(0) == 0
    assert popcount(0b101101) == 4

    # clz
    assert clz(0, 32) == 32
    assert clz(1, 32) == 31
    assert clz(0x80000000, 32) == 0
    assert clz(0x00010000, 32) == 15

    # ctz
    assert ctz(0, 32) == 32
    assert ctz(1, 32) == 0
    assert ctz(0x80000000, 32) == 31
    assert ctz(0b1000, 32) == 3


def test_byte_swapping():
    assert bswap16(0x1234) == 0x3412
    assert bswap32(0x12345678) == 0x78563412
    assert bswap64(0x1122334455667788) == 0x8877665544332211
