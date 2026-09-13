"""
Pure-Python low-level pixel manipulation and color arithmetic primitives.
Zero external binary dependencies, operating directly on raw byte buffers.
Powered by MioROM.
"""

from __future__ import annotations

from typing import Tuple, Union, Optional


def interpolate_color(
    c1: Tuple[int, int, int, int],
    c2: Tuple[int, int, int, int],
    t: float,
) -> Tuple[int, int, int, int]:
    """
    Linearly interpolates between two RGBA colors where t is in [0.0, 1.0].
    Returns (r, g, b, a) clamped to 0..255.
    """
    t_clamped = max(0.0, min(1.0, float(t)))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t_clamped),
        int(c1[1] + (c2[1] - c1[1]) * t_clamped),
        int(c1[2] + (c2[2] - c1[2]) * t_clamped),
        int(c1[3] + (c2[3] - c1[3]) * t_clamped),
    )


def apply_vertical_gradient(
    mask_bytes: bytes,
    width: int,
    height: int,
    top_color: Tuple[int, int, int, int],
    bottom_color: Tuple[int, int, int, int],
) -> bytes:
    """
    Applies a vertical linear color gradient across an 8-bit alpha mask (width*height bytes)
    or 32-bit RGBA bytes.
    Returns a new 32-bit RGBA bytes buffer of size width * height * 4.
    """
    out = bytearray(width * height * 4)
    is_l = (len(mask_bytes) == width * height)

    for y in range(height):
        t = y / max(1, height - 1)
        r, g, b, a = interpolate_color(top_color, bottom_color, t)
        for x in range(width):
            m_idx = y * width + x if is_l else (y * width + x) * 4 + 3
            mask_val = mask_bytes[m_idx]
            out_idx = (y * width + x) * 4

            if mask_val == 0:
                out[out_idx : out_idx + 4] = b"\x00\x00\x00\x00"
            else:
                out[out_idx] = r
                out[out_idx + 1] = g
                out[out_idx + 2] = b
                out[out_idx + 3] = (a * mask_val) // 255

    return bytes(out)


def apply_outline_1px(
    rgba_bytes: bytes,
    width: int,
    height: int,
    outline_color: Tuple[int, int, int, int],
    alpha_threshold: int = 30,
) -> bytes:
    """
    Adds a 1-pixel 8-connected outline around opaque pixels in a raw 32-bit RGBA buffer.
    Preserves inner opaque pixels.
    Returns a new 32-bit RGBA bytes buffer of size width * height * 4.
    """
    out = bytearray(rgba_bytes)
    r_out, g_out, b_out, a_out = outline_color

    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            # Only consider transparent or low-alpha pixels for the outline
            if rgba_bytes[idx + 3] <= alpha_threshold:
                # Check 8-neighborhood for an opaque pixel
                has_neighbor = False
                for dy in (-1, 0, 1):
                    ny = y + dy
                    if 0 <= ny < height:
                        for dx in (-1, 0, 1):
                            if dy == 0 and dx == 0:
                                continue
                            nx = x + dx
                            if 0 <= nx < width:
                                n_idx = (ny * width + nx) * 4
                                if rgba_bytes[n_idx + 3] > alpha_threshold:
                                    has_neighbor = True
                                    break
                    if has_neighbor:
                        break

                if has_neighbor:
                    out[idx] = r_out
                    out[idx + 1] = g_out
                    out[idx + 2] = b_out
                    out[idx + 3] = a_out

    return bytes(out)
