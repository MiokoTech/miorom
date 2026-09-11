from typing import List, Optional, Sequence, Union


def combine_split_words(
    low_bytes: Sequence[int],
    high_bytes: Sequence[int],
    bank_bytes: Optional[Sequence[int]] = None,
    endian: str = "<",
) -> List[int]:
    """
    Combines separate byte arrays (e.g. split pointer tables in 8/16-bit ROMs)
    into 16-bit or 24-bit integer words.
    """
    if len(low_bytes) != len(high_bytes):
        raise ValueError(
            f"Length mismatch: low_bytes ({len(low_bytes)}) != high_bytes ({len(high_bytes)})"
        )
    if bank_bytes is not None and len(bank_bytes) != len(low_bytes):
        raise ValueError(
            f"Length mismatch: bank_bytes ({len(bank_bytes)}) != low_bytes ({len(low_bytes)})"
        )

    is_le = endian == "<"
    total = len(low_bytes)
    words: List[int] = []

    for i in range(total):
        lo = low_bytes[i] & 0xFF
        hi = high_bytes[i] & 0xFF

        if bank_bytes is not None:
            bank = bank_bytes[i] & 0xFF
            if is_le:
                words.append((bank << 16) | (hi << 8) | lo)
            else:
                words.append((lo << 16) | (hi << 8) | bank)
        else:
            if is_le:
                words.append((hi << 8) | lo)
            else:
                words.append((lo << 8) | hi)

    return words


def split_words(
    words: Sequence[int],
    word_size: int = 2,
    endian: str = "<",
) -> List[bytes]:
    """
    Decomposes integer words into separate byte arrays per byte lane.
    For word_size=2: returns [byte_0, byte_1].
    """
    if word_size not in (2, 3, 4):
        raise ValueError(f"word_size must be 2, 3, or 4, got {word_size}")

    lanes: List[bytearray] = [bytearray() for _ in range(word_size)]
    is_le = endian == "<"

    for w in words:
        for lane_idx in range(word_size):
            shift = (lane_idx * 8) if is_le else ((word_size - 1 - lane_idx) * 8)
            lanes[lane_idx].append((w >> shift) & 0xFF)

    return [bytes(lane) for lane in lanes]


def deinterleave_channels(
    data: Union[bytes, bytearray, memoryview],
    num_channels: int,
    word_size: int = 1,
) -> List[bytes]:
    """
    Deinterleaves a multi-channel stream into independent channel byte streams.
    Commonly used for even/odd arcade ROM splitting and stereo audio demuxing.
    """
    if num_channels <= 0:
        raise ValueError(f"num_channels must be positive, got {num_channels}")
    if word_size <= 0:
        raise ValueError(f"word_size must be positive, got {word_size}")

    frame_size = num_channels * word_size
    if len(data) % frame_size != 0:
        raise ValueError(
            f"Data length ({len(data)}) must be a multiple of frame size ({frame_size})"
        )

    channels: List[bytearray] = [bytearray() for _ in range(num_channels)]
    total_frames = len(data) // frame_size

    for frame in range(total_frames):
        base = frame * frame_size
        for ch in range(num_channels):
            start = base + ch * word_size
            channels[ch].extend(data[start : start + word_size])

    return [bytes(ch) for ch in channels]


def interleave_channels(
    channels: Sequence[Union[bytes, bytearray, memoryview]],
    word_size: int = 1,
) -> bytes:
    """
    Combines independent channel byte streams back into an interleaved multi-channel stream.
    """
    if not channels:
        return b""
    if word_size <= 0:
        raise ValueError(f"word_size must be positive, got {word_size}")

    channel_len = len(channels[0])
    for i, ch in enumerate(channels):
        if len(ch) != channel_len:
            raise ValueError(f"Channel {i} length ({len(ch)}) does not match channel 0 ({channel_len})")
        if len(ch) % word_size != 0:
            raise ValueError(f"Channel {i} length is not a multiple of word_size {word_size}")

    num_channels = len(channels)
    total_words = channel_len // word_size
    out = bytearray()

    for w in range(total_words):
        start = w * word_size
        for ch in range(num_channels):
            out.extend(channels[ch][start : start + word_size])

    return bytes(out)
