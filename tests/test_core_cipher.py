import pytest
from miorom.core.cipher import (
    xor_bytes,
    rolling_xor,
    invert_bytes,
    add_cipher,
    crack_single_byte_xor,
)


def test_xor_bytes_roundtrip():
    plain = b"MioROM Secret Dialogue Archive 1996"
    key = b"\xDE\xAD\xBE\xEF"

    encrypted = xor_bytes(plain, key)
    assert encrypted != plain
    decrypted = xor_bytes(encrypted, key)
    assert decrypted == plain

    with pytest.raises(ValueError):
        xor_bytes(plain, b"")


def test_rolling_xor_roundtrip():
    plain = b"Super Mario RPG / Final Fantasy VII Script Block"
    seed = 0x5A
    step = 7

    encrypted = rolling_xor(plain, seed, step)
    assert encrypted != plain
    decrypted = rolling_xor(encrypted, seed, step)
    assert decrypted == plain


def test_invert_bytes():
    plain = b"\x00\x55\xAA\xFF"
    inverted = invert_bytes(plain)
    assert inverted == b"\xFF\xAA\x55\x00"
    assert invert_bytes(inverted) == plain


def test_add_cipher_roundtrip():
    plain = b"Hidden Item Table: Excalibur, Ragnarok, Masamune"
    key = b"\x03\x07\x0F"

    enc = add_cipher(plain, key, decrypt=False)
    assert enc != plain
    dec = add_cipher(enc, key, decrypt=True)
    assert dec == plain


def test_crack_single_byte_xor():
    message = b"Congratulations! You defeated the final boss and saved the kingdom."
    secret_key = 0x77

    obfuscated = bytes([b ^ secret_key for b in message])
    guessed_key, score = crack_single_byte_xor(obfuscated)

    assert guessed_key == secret_key
    assert score > 0.95
    decrypted = bytes([b ^ guessed_key for b in obfuscated])
    assert decrypted == message
