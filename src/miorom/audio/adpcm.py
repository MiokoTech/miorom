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
    def encode_ima(
        cls,
        samples: List[int],
        initial_predictor: int = 0,
        initial_index: int = 0,
    ) -> Tuple[bytes, int, int]:
        """
        Compresses signed 16-bit PCM audio samples into 4-bit IMA-ADPCM bytes.
        Returns a tuple of (adpcm_bytes, final_predictor, final_index).
        """
        predictor = initial_predictor
        step_index = max(0, min(88, initial_index))
        nibbles: List[int] = []

        for sample in samples:
            diff = sample - predictor
            sign = 0
            if diff < 0:
                sign = 8
                diff = -diff

            step = cls.STEP_TABLE[step_index]
            delta = 0
            vpdiff = step >> 3

            if diff >= step:
                delta |= 4
                diff -= step
                vpdiff += step
            step_half = step >> 1
            if diff >= step_half:
                delta |= 2
                diff -= step_half
                vpdiff += step_half
            step_quarter = step >> 2
            if diff >= step_quarter:
                delta |= 1
                vpdiff += step_quarter

            if sign:
                predictor -= vpdiff
            else:
                predictor += vpdiff

            predictor = max(-32768, min(32767, predictor))
            nibbles.append(sign | delta)

            step_index += cls.INDEX_TABLE[delta]
            step_index = max(0, min(88, step_index))

        # Pack lower nibble first, then upper nibble
        adpcm_bytes = bytearray()
        for i in range(0, len(nibbles), 2):
            low = nibbles[i]
            high = nibbles[i + 1] if i + 1 < len(nibbles) else 0
            adpcm_bytes.append(low | (high << 4))

        return bytes(adpcm_bytes), predictor, step_index

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
        from miorom.audio.wav_codec import WavCodec

        return WavCodec.encode(samples, sample_rate=sample_rate, channels=channels, bits_per_sample=16)

    @classmethod
    def read_wav(cls, data: bytes) -> dict:
        """
        Parses standard RIFF/WAVE audio data into channels, sample rate, and PCM samples.
        """
        from miorom.audio.wav_codec import WavCodec

        try:
            sound = WavCodec.decode(data)
        except Exception as e:
            raise ValueError(f"Invalid WAV file container: {e}") from e

        return {
            "channels": sound.channels,
            "sample_rate": sound.sample_rate,
            "bits_per_sample": sound.bits_per_sample,
            "samples": sound.samples,
        }

