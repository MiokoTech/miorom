from typing import Tuple


def rol(val: int, shift: int, bits: int = 8) -> int:
    """Bitwise rotate left within a specified bit width."""
    mask = (1 << bits) - 1
    val &= mask
    shift %= bits
    if shift == 0:
        return val
    return ((val << shift) | (val >> (bits - shift))) & mask


def ror(val: int, shift: int, bits: int = 8) -> int:
    """Bitwise rotate right within a specified bit width."""
    mask = (1 << bits) - 1
    val &= mask
    shift %= bits
    if shift == 0:
        return val
    return ((val >> shift) | (val << (bits - shift))) & mask


def bit_reverse(val: int, bits: int) -> int:
    """Reverses the bit order of an integer of arbitrary bit width."""
    mask = (1 << bits) - 1
    val &= mask
    res = 0
    for _ in range(bits):
        res = (res << 1) | (val & 1)
        val >>= 1
    return res


def bit_reverse8(val: int) -> int:
    """Reverses the bit order of an 8-bit integer."""
    val &= 0xFF
    val = ((val & 0xF0) >> 4) | ((val & 0x0F) << 4)
    val = ((val & 0xCC) >> 2) | ((val & 0x33) << 2)
    val = ((val & 0xAA) >> 1) | ((val & 0x55) << 1)
    return val


def bit_reverse16(val: int) -> int:
    """Reverses the bit order of a 16-bit integer."""
    val &= 0xFFFF
    b0 = bit_reverse8(val & 0xFF)
    b1 = bit_reverse8((val >> 8) & 0xFF)
    return (b0 << 8) | b1


def bit_reverse32(val: int) -> int:
    """Reverses the bit order of a 32-bit integer."""
    val &= 0xFFFFFFFF
    w0 = bit_reverse16(val & 0xFFFF)
    w1 = bit_reverse16((val >> 16) & 0xFFFF)
    return (w0 << 16) | w1


def swap_nibbles(val: int) -> int:
    """Swaps the high and low 4-bit nibbles of an 8-bit byte."""
    val &= 0xFF
    return ((val & 0x0F) << 4) | ((val >> 4) & 0x0F)


def pack_nibbles(high: int, low: int) -> int:
    """Packs two 4-bit integers into a single 8-bit byte."""
    return ((high & 0x0F) << 4) | (low & 0x0F)


def unpack_nibbles(val: int) -> Tuple[int, int]:
    """Unpacks an 8-bit byte into a (high_nibble, low_nibble) pair."""
    return (val >> 4) & 0x0F, val & 0x0F


def sign_extend(val: int, bits: int) -> int:
    """Sign-extends an unsigned integer of specified bit width into a signed Python int."""
    mask = (1 << bits) - 1
    val &= mask
    sign_bit = 1 << (bits - 1)
    if val & sign_bit:
        return val - (1 << bits)
    return val


def popcount(val: int) -> int:
    """Counts the number of set bits (1s) in a non-negative integer."""
    if val < 0:
        raise ValueError("popcount requires a non-negative integer")
    return val.bit_count()


def clz(val: int, bits: int = 32) -> int:
    """Counts leading zero bits in a specified bit width."""
    mask = (1 << bits) - 1
    val &= mask
    if val == 0:
        return bits
    return bits - val.bit_length()


def ctz(val: int, bits: int = 32) -> int:
    """Counts trailing zero bits in a specified bit width."""
    mask = (1 << bits) - 1
    val &= mask
    if val == 0:
        return bits
    return (val & -val).bit_length() - 1


def bswap16(val: int) -> int:
    """Swaps endianness bytes of a 16-bit word."""
    val &= 0xFFFF
    return ((val & 0xFF) << 8) | ((val >> 8) & 0xFF)


def bswap32(val: int) -> int:
    """Swaps endianness bytes of a 32-bit dword."""
    val &= 0xFFFFFFFF
    return (
        ((val & 0x000000FF) << 24)
        | ((val & 0x0000FF00) << 8)
        | ((val & 0x00FF0000) >> 8)
        | ((val >> 24) & 0xFF)
    )


def bswap64(val: int) -> int:
    """Swaps endianness bytes of a 64-bit qword."""
    val &= 0xFFFFFFFFFFFFFFFF
    d0 = bswap32(val & 0xFFFFFFFF)
    d1 = bswap32((val >> 32) & 0xFFFFFFFF)
    return (d0 << 32) | d1
