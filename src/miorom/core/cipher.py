from typing import Tuple, Union


def xor_bytes(data: Union[bytes, bytearray, memoryview], key: bytes) -> bytes:
    """Performs repeating multi-byte XOR encryption/decryption."""
    if not key:
        raise ValueError("XOR key cannot be empty")

    key_len = len(key)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i % key_len]
    return bytes(out)


def rolling_xor(
    data: Union[bytes, bytearray, memoryview],
    seed: int,
    step: int = 1,
) -> bytes:
    """
    Applies a rolling-key XOR stream where key evolves per byte:
    K_(i+1) = (K_i + step) mod 256.
    """
    cur_key = seed & 0xFF
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ cur_key
        cur_key = (cur_key + step) & 0xFF
    return bytes(out)


def invert_bytes(data: Union[bytes, bytearray, memoryview]) -> bytes:
    """Applies bitwise NOT (~b & 0xFF) to each byte."""
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = (~b) & 0xFF
    return bytes(out)


def add_cipher(
    data: Union[bytes, bytearray, memoryview],
    key: bytes,
    decrypt: bool = False,
) -> bytes:
    """
    Applies repeating byte addition (or subtraction when decrypt=True) modulo 256.
    """
    if not key:
        raise ValueError("Cipher key cannot be empty")

    key_len = len(key)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        k = key[i % key_len]
        if decrypt:
            out[i] = (b - k) & 0xFF
        else:
            out[i] = (b + k) & 0xFF
    return bytes(out)


def crack_single_byte_xor(data: Union[bytes, bytearray, memoryview]) -> Tuple[int, float]:
    """
    Heuristically cracks single-byte XOR obfuscation by scoring ASCII readability.
    Returns (best_key, confidence_score) where score is ratio of printable characters.
    """
    if not data:
        return 0, 0.0

    best_key = 0
    best_score = -1.0
    total = len(data)

    printable_set = set(b" abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?'\"-\n\r\t")

    for candidate_key in range(256):
        printable_count = 0
        for b in data:
            decrypted = b ^ candidate_key
            if decrypted in printable_set:
                printable_count += 1

        score = printable_count / total
        if score > best_score:
            best_score = score
            best_key = candidate_key

    return best_key, best_score
