import struct
from typing import List, Tuple


class ADPCMCodec:
    """
    IMA-ADPCM audio decoder and standard PCM WAV container builder.
    Commonly used for game sound effects, voices, and instruments (NDS SWAV, PS1, GameCube).
    """

    INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]

    STEP_TABLE = [
        7, 8, 9, 10, 11, 12, 13, 14, 16, 17,
        19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
        50, 55, 60, 66, 73, 80, 88, 97, 107, 118,
        130, 143, 157, 173, 190, 209, 230, 253, 279, 307,
        337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
        876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066,
        2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
        5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
        15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767
    ]

    @classmethod
    def decode_ima(
        cls,
        data: bytes,
        initial_predictor: int = 0,
        initial_index: int = 0,
    ) -> List[int]:
        """
        Decodes raw IMA-ADPCM bytes into signed 16-bit PCM audio samples (-32768 to 32767).
        """
        predictor = initial_predictor
        step_index = max(0, min(88, initial_index))
        samples: List[int] = []

        for byte in data:
            # Process lower nibble first, then upper nibble
            for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
                step = cls.STEP_TABLE[step_index]

                # Update index
                step_index += cls.INDEX_TABLE[nibble & 0x07]
                step_index = max(0, min(88, step_index))

                # Compute difference
                diff = step >> 3
                if nibble & 1:
                    diff += step >> 2
                if nibble & 2:
                    diff += step >> 1
                if nibble & 4:
                    diff += step

                if nibble & 8:
                    predictor -= diff
                else:
                    predictor += diff

                # Clamp 16-bit
                predictor = max(-32768, min(32767, predictor))
                samples.append(predictor)

        return samples

    @classmethod
    def build_wav(
        cls,
        samples: List[int],
        sample_rate: int = 22050,
        channels: int = 1,
    ) -> bytes:
        """
        Encapsulates 16-bit PCM samples into a standard RIFF/WAVE file binary.
        """
        bits_per_sample = 16
        block_align = channels * (bits_per_sample // 8)
        byte_rate = sample_rate * block_align
        data_bytes = bytearray()
        for s in samples:
            data_bytes.extend(struct.pack("<h", s))

        data_size = len(data_bytes)
        riff_size = 36 + data_size

        header = bytearray()
        # RIFF header
        header.extend(b"RIFF")
        header.extend(struct.pack("<I", riff_size))
        header.extend(b"WAVE")

        # fmt subchunk
        header.extend(b"fmt ")
        header.extend(struct.pack("<I", 16))          # Subchunk1Size
        header.extend(struct.pack("<H", 1))           # AudioFormat (PCM = 1)
        header.extend(struct.pack("<H", channels))
        header.extend(struct.pack("<I", sample_rate))
        header.extend(struct.pack("<I", byte_rate))
        header.extend(struct.pack("<H", block_align))
        header.extend(struct.pack("<H", bits_per_sample))

        # data subchunk
        header.extend(b"data")
        header.extend(struct.pack("<I", data_size))

        return bytes(header + data_bytes)
