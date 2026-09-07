import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


FILTER_K1 = (0, 60, 115, 98, 122)
FILTER_K2 = (0, 0, -52, -55, -60)


@dataclass
class CdXaChannelState:
    prev1: int = 0
    prev2: int = 0

    def reset(self):
        self.prev1 = 0
        self.prev2 = 0


class CdXaDecoder:
    """
    PlayStation / CD-ROM XA ADPCM audio decoder.
    Decodes CD-XA Mode 2 Form 2 audio sectors (18 sound groups x 128 bytes = 2304 bytes)
    into 16-bit signed PCM audio.
    """

    def __init__(self):
        self.left_state = CdXaChannelState()
        self.right_state = CdXaChannelState()

    def reset(self):
        self.left_state.reset()
        self.right_state.reset()

    def decode_sector(
        self,
        sector_bytes: bytes,
        stereo: bool = True,
        bits: int = 4,
    ) -> bytes:
        """
        Decode a single CD-XA audio sector (accepts 2352 raw, 2336 subheader-included, or 2304 raw audio bytes).
        Returns 16-bit little-endian PCM byte buffer.
        """
        if len(sector_bytes) >= 2352:
            # Raw CD-ROM sector: audio payload starts at offset 0x18 (24)
            payload = sector_bytes[0x18:0x18 + 2304]
        elif len(sector_bytes) >= 2336:
            # Subheader-included sector: audio payload starts at offset 8
            payload = sector_bytes[8:8 + 2304]
        elif len(sector_bytes) >= 2304:
            payload = sector_bytes[:2304]
        else:
            payload = sector_bytes.ljust(2304, b"\x00")

        out_pcm = bytearray()

        # 18 sound groups of 128 bytes each
        for group_idx in range(18):
            group_offset = group_idx * 128
            group_data = payload[group_offset:group_offset + 128]
            if len(group_data) < 128:
                break

            pcm_group = self._decode_sound_group(group_data, stereo, bits)
            out_pcm.extend(pcm_group)

        return bytes(out_pcm)

    def _decode_sound_group(
        self,
        group_data: bytes,
        stereo: bool,
        bits: int,
    ) -> bytes:
        """Decode a 128-byte CD-XA sound group."""
        if bits != 4:
            # Fallback 4-bit standard
            bits = 4

        # Read header parameters for the 8 sound units
        # Units 0..3 from data[0..3], Units 4..7 from data[8..11]
        shifts = [0] * 8
        filters = [0] * 8
        for u in range(4):
            hdr = group_data[u]
            shifts[u] = min(12, hdr & 0x0F)
            filters[u] = min(4, (hdr >> 4) & 0x07)

            hdr_hi = group_data[8 + u]
            shifts[4 + u] = min(12, hdr_hi & 0x0F)
            filters[4 + u] = min(4, (hdr_hi >> 4) & 0x07)

        # Decode each sound unit (28 samples per unit)
        unit_samples: List[List[int]] = [[] for _ in range(8)]

        for s in range(28):
            row_offset = 16 + s * 4
            b0 = group_data[row_offset]
            b1 = group_data[row_offset + 1]
            b2 = group_data[row_offset + 2]
            b3 = group_data[row_offset + 3]

            # Nibble distribution:
            # b0: low nibble -> unit 0, high nibble -> unit 1
            # b1: low nibble -> unit 2, high nibble -> unit 3
            # b2: low nibble -> unit 4, high nibble -> unit 5
            # b3: low nibble -> unit 6, high nibble -> unit 7
            n0 = b0 & 0x0F
            n1 = (b0 >> 4) & 0x0F
            n2 = b1 & 0x0F
            n3 = (b1 >> 4) & 0x0F
            n4 = b2 & 0x0F
            n5 = (b2 >> 4) & 0x0F
            n6 = b3 & 0x0F
            n7 = (b3 >> 4) & 0x0F

            nibbles = (n0, n1, n2, n3, n4, n5, n6, n7)
            for u in range(8):
                nib = nibbles[u]
                # Sign extend 4-bit nibble
                if nib >= 8:
                    nib -= 16

                shift = shifts[u]
                filt = filters[u]
                k1 = FILTER_K1[filt]
                k2 = FILTER_K2[filt]

                state = self.left_state if (stereo and (u % 2 == 0)) else (
                    self.right_state if stereo else self.left_state
                )

                sample_enc = nib << 12
                sample_dec = sample_enc >> shift
                pred = (k1 * state.prev1 + k2 * state.prev2 + 32) >> 6
                sample = sample_dec + pred

                # Clamp to 16-bit signed range [-32768, 32767]
                if sample > 32767:
                    sample = 32767
                elif sample < -32768:
                    sample = -32768

                state.prev2 = state.prev1
                state.prev1 = sample
                unit_samples[u].append(sample)

        # Interleave output samples
        out = bytearray()
        if stereo:
            # Units (0, 1), (2, 3), (4, 5), (6, 7) are stereo pairs
            for pair in ((0, 1), (2, 3), (4, 5), (6, 7)):
                l_samples = unit_samples[pair[0]]
                r_samples = unit_samples[pair[1]]
                for left, right in zip(l_samples, r_samples):
                    out.extend(struct.pack("<hh", left, right))
        else:
            # Sequential units 0..7
            for u in range(8):
                for val in unit_samples[u]:
                    out.extend(struct.pack("<h", val))

        return bytes(out)


def decode_cdxa_sector(
    sector_data: bytes,
    stereo: bool = True,
    bits: int = 4,
) -> bytes:
    """Convenience helper to decode a single CD-XA audio sector to 16-bit PCM."""
    decoder = CdXaDecoder()
    return decoder.decode_sector(sector_data, stereo=stereo, bits=bits)


def cdxa_to_wav(
    sectors: List[bytes],
    sample_rate: int = 37800,
    stereo: bool = True,
    bits: int = 4,
) -> bytes:
    """
    Decode a sequence of CD-XA audio sectors and wrap into standard RIFF/WAV format.
    Default CD-XA rate is 37800 Hz stereo or 18900 Hz mono.
    """
    decoder = CdXaDecoder()
    pcm_chunks = []
    for sec in sectors:
        pcm_chunks.append(decoder.decode_sector(sec, stereo=stereo, bits=bits))
    pcm_data = b"".join(pcm_chunks)

    num_channels = 2 if stereo else 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
    block_align = num_channels * (bits_per_sample // 8)

    # RIFF WAV header (44 bytes)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm_data),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        len(pcm_data),
    )
    return header + pcm_data
