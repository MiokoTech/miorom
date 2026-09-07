import math
import struct
from typing import Any, List, Optional, Tuple


# Standard 8x8 Zigzag ordering
ZIGZAG = (
     0,  1,  8, 16,  9,  2,  3, 10,
    17, 24, 32, 25, 18, 11,  4,  5,
    12, 19, 26, 33, 40, 48, 41, 34,
    27, 20, 13,  6,  7, 14, 21, 28,
    35, 42, 49, 56, 57, 50, 43, 36,
    29, 22, 15, 23, 30, 37, 44, 51,
    58, 59, 52, 45, 38, 31, 39, 46,
    53, 60, 61, 54, 47, 55, 62, 63,
)

# Standard PS1 MDEC default quantization table
DEFAULT_LUMA_QUANT = [
     2, 16, 19, 22, 26, 27, 29, 34,
    16, 16, 22, 24, 27, 29, 34, 37,
    19, 22, 26, 27, 29, 34, 34, 38,
    22, 22, 26, 27, 29, 34, 37, 40,
    22, 26, 27, 29, 32, 35, 40, 48,
    26, 27, 29, 32, 35, 40, 48, 58,
    26, 27, 29, 34, 38, 46, 56, 69,
    27, 29, 35, 38, 46, 56, 69, 83,
]

# Precomputed cosine tables for 8x8 IDCT
COS_TABLE = [[math.cos((2 * i + 1) * u * math.pi / 16.0) for u in range(8)] for i in range(8)]
C_COEFF = [1.0 / math.sqrt(2.0) if u == 0 else 1.0 for u in range(8)]


def idct_8x8(freq_block: List[List[float]]) -> List[List[float]]:
    """Separable 2D Inverse Discrete Cosine Transform on 8x8 block."""
    temp = [[0.0] * 8 for _ in range(8)]
    for y in range(8):
        row = freq_block[y]
        for x in range(8):
            temp[y][x] = 0.5 * sum(C_COEFF[u] * row[u] * COS_TABLE[x][u] for u in range(8))

    spatial = [[0.0] * 8 for _ in range(8)]
    for x in range(8):
        col = [temp[y][x] for y in range(8)]
        for y in range(8):
            spatial[y][x] = 0.5 * sum(C_COEFF[v] * col[v] * COS_TABLE[y][v] for v in range(8))

    return spatial


class MdecDecoder:
    """
    PlayStation 1 MDEC (Macroblock Decoder) bitstream decoder.
    Decompresses MDEC DCT run-length encoded macroblock streams into 24-bit RGB images.
    """

    def __init__(self, quant_table: Optional[List[int]] = None):
        self.quant_table = quant_table or DEFAULT_LUMA_QUANT

    def decode_block(
        self,
        words_iter,
        is_chroma: bool = False,
    ) -> List[List[float]]:
        """Decode a single 8x8 DCT block from 16-bit halfwords."""
        coeffs = [0.0] * 64

        try:
            first_word = next(words_iter)
        except StopIteration:
            return [[0.0] * 8 for _ in range(8)]

        if first_word == 0xFE00:
            # Empty block
            return [[0.0] * 8 for _ in range(8)]

        # DC coefficient (10-bit signed)
        dc_val = first_word & 0x3FF
        if dc_val >= 512:
            dc_val -= 1024
        coeffs[0] = float(dc_val * self.quant_table[0])

        # AC coefficients
        coeff_idx = 0
        for word in words_iter:
            if word == 0xFE00:
                break

            run = (word >> 10) & 0x3F
            level = word & 0x3FF
            if level >= 512:
                level -= 1024

            coeff_idx += run + 1
            if coeff_idx >= 64:
                break

            pos = ZIGZAG[coeff_idx]
            coeffs[pos] = float(level * self.quant_table[pos])

        # Convert 1D 64 coefficients into 8x8 matrix
        matrix = [coeffs[y * 8:(y + 1) * 8] for y in range(8)]
        return idct_8x8(matrix)

    def decode_stream(
        self,
        bs_data: bytes,
        width: int,
        height: int,
    ) -> bytes:
        """
        Decode a complete MDEC bitstream into raw RGB24 bytes (width * height * 3).
        """
        # Ensure 16-bit halfword alignment
        num_words = len(bs_data) // 2
        words = struct.unpack_from(f"<{num_words}H", bs_data, 0)
        words_iter = iter(words)

        mb_width = (width + 15) // 16
        mb_height = (height + 15) // 16

        out_rgb = bytearray(width * height * 3)

        for mby in range(mb_height):
            for mbx in range(mb_width):
                # 6 blocks per macroblock: Cr, Cb, Y1, Y2, Y3, Y4
                cr_block = self.decode_block(words_iter, is_chroma=True)
                cb_block = self.decode_block(words_iter, is_chroma=True)
                y1 = self.decode_block(words_iter, is_chroma=False)
                y2 = self.decode_block(words_iter, is_chroma=False)
                y3 = self.decode_block(words_iter, is_chroma=False)
                y4 = self.decode_block(words_iter, is_chroma=False)

                # Assemble 16x16 macroblock pixels
                y_quads = (
                    (y1, 0, 0),
                    (y2, 8, 0),
                    (y3, 0, 8),
                    (y4, 8, 8),
                )

                for y_block, qx, qy in y_quads:
                    for py in range(8):
                        img_y = mby * 16 + qy + py
                        if img_y >= height:
                            continue

                        for px in range(8):
                            img_x = mbx * 16 + qx + px
                            if img_x >= width:
                                continue

                            # Chroma is 8x8 upscaled 2x to 16x16
                            cx = (qx + px) // 2
                            cy = (qy + py) // 2

                            y_val = y_block[py][px] + 128.0
                            cb_val = cb_block[cy][cx]
                            cr_val = cr_block[cy][cx]

                            # ITU-R BT.601 YCbCr to RGB conversion
                            r = int(y_val + 1.402 * cr_val)
                            g = int(y_val - 0.344136 * cb_val - 0.714136 * cr_val)
                            b = int(y_val + 1.772 * cb_val)

                            # Clamp to [0, 255]
                            r = max(0, min(255, r))
                            g = max(0, min(255, g))
                            b = max(0, min(255, b))

                            pixel_offset = (img_y * width + img_x) * 3
                            out_rgb[pixel_offset] = r
                            out_rgb[pixel_offset + 1] = g
                            out_rgb[pixel_offset + 2] = b

        return bytes(out_rgb)

    def to_image(self, bs_data: bytes, width: int, height: int) -> Any:
        """Decode bitstream and return a Pillow Image object (requires Pillow)."""
        rgb_data = self.decode_stream(bs_data, width, height)
        try:
            from PIL import Image
            return Image.frombytes("RGB", (width, height), rgb_data)
        except ImportError:
            return rgb_data
