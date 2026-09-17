"""
tests.test_platforms_wii_wad
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive unit tests for Nintendo Wii WAD package container,
zero-dependency AES-128-CBC cipher, Ticket/TMD cryptor, and U8Archive bridge.
"""

import hashlib

import pytest

from miorom.core import schema
from miorom.errors import ParseError
from miorom.platforms.wii.u8 import (
    U8Archive,
    WADContentRecord,
    WADFile,
    WADTicket,
    WADTmd,
    aes128_cbc_decrypt,
    aes128_cbc_encrypt,
)


def test_aes128_cbc_known_vectors():
    """Verifies pure-Python AES-128-CBC cipher against standard NIST vectors."""
    # NIST SP 800-38A CBC-AES128 Test Vector
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plaintext = bytes.fromhex(
        "6bc1bee22e409f96e93d7e117393172a"
        "ae2d8a571e03ac9c9eb76fac45af8e51"
        "30c81c46a35ce411e5fbc1191a0a52ef"
        "f69f2445df4f9b17ad2b417be66c3710"
    )
    expected_cipher = bytes.fromhex(
        "7649abac8119b246cee98e9b12e9197d"
        "5086cb9b507219ee95db113a917678b2"
        "73bed6b8e3c1743b7116e69e22229516"
        "3ff1caa1681fac09120eca307586e1a7"
    )

    ciphertext = aes128_cbc_encrypt(plaintext, key, iv)
    assert ciphertext == expected_cipher

    decrypted = aes128_cbc_decrypt(ciphertext, key, iv)
    assert decrypted == plaintext


def test_u8_archive_in_memory_mutable_api():
    """Verifies in-memory dictionary-like mutation and serialization on U8Archive."""
    files = {
        "text/message.bmg": b"ORIGINAL_JAPANESE_TEXT_0123456789",
        "layout/title.brlyt": b"BRLYT_SAMPLE_LAYOUT_BYTES",
    }
    u8 = U8Archive(files)
    assert len(u8) == 2
    assert "text/message.bmg" in u8

    # Modify an entry
    u8["text/message.bmg"] = b"TRANSLATED_ENGLISH_TEXT_ABCDEF"
    assert u8["text/message.bmg"] == b"TRANSLATED_ENGLISH_TEXT_ABCDEF"

    # Add a new file
    u8["font/custom.brfnt"] = b"NEW_FONT_DATA"
    assert len(u8) == 3

    # Serialize to bytes and parse back
    raw_u8 = u8.to_bytes()
    assert U8Archive.is_u8(raw_u8)

    loaded_u8 = U8Archive.from_bytes(raw_u8)
    assert len(loaded_u8) == 3
    assert loaded_u8["text/message.bmg"] == b"TRANSLATED_ENGLISH_TEXT_ABCDEF"
    assert loaded_u8["layout/title.brlyt"] == b"BRLYT_SAMPLE_LAYOUT_BYTES"
    assert loaded_u8["font/custom.brfnt"] == b"NEW_FONT_DATA"


def _build_dummy_ticket(title_id: bytes, common_key: bytes, title_key: bytes) -> WADTicket:
    """Helper to synthesize a standard 0x2A4-byte Wii Ticket."""
    raw = bytearray(0x2A4)
    # RSA-2048 signature
    schema.pack_into(">I", raw, 0, 0x10001)
    # Console ID
    schema.pack_into(">I", raw, 0x1C7, 0x12345678)
    # Title ID
    raw[0x1CB:0x1D3] = title_id
    # Common key index (0 = standard)
    raw[0x1DF] = 0

    tik = WADTicket.from_bytes(bytes(raw))
    tik.encrypt_title_key(title_key, common_key)
    return tik


def _build_dummy_tmd(title_id: bytes, content_sizes_and_hashes: list) -> WADTmd:
    """Helper to synthesize a standard Wii TMD."""
    num_contents = len(content_sizes_and_hashes)
    raw = bytearray(0x1E4 + num_contents * 36)
    # Signature
    schema.pack_into(">I", raw, 0, 0x10001)
    # Title ID
    raw[0x18C:0x194] = title_id
    # Title version
    schema.pack_into(">H", raw, 0x1DC, 1)
    # Number of contents
    schema.pack_into(">H", raw, 0x1DE, num_contents)
    # Boot index
    schema.pack_into(">H", raw, 0x1E0, 0)

    contents: list = []
    rec_off = 0x1E4
    for idx, (cid, ctype, sz, sha) in enumerate(content_sizes_and_hashes):
        schema.pack_into(">IHHQ", raw, rec_off, cid, idx, ctype, sz)
        raw[rec_off + 16 : rec_off + 36] = sha
        contents.append(WADContentRecord(cid, idx, ctype, sz, sha))
        rec_off += 36

    return WADTmd(raw, title_id, title_version=1, boot_index=0, contents=contents)


def test_wad_ticket_parsing_and_key_crypt():
    """Verifies Wii Ticket title key encryption and decryption."""
    common_key = b"WII_COMMON_KEY_!"
    title_key = b"SECRET_TITLE_KEY"
    title_id = b"00010001"

    ticket = _build_dummy_ticket(title_id, common_key, title_key)
    assert ticket.common_key_index == 0
    assert ticket.console_id == 0x12345678
    assert ticket.title_id == title_id

    decrypted_key = ticket.decrypt_title_key(common_key)
    assert decrypted_key == title_key

    # Re-encrypt with different key
    new_title_key = b"ANOTHER_TITLEKEY"
    ticket.encrypt_title_key(new_title_key, common_key)
    assert ticket.decrypt_title_key(common_key) == new_title_key


def test_wad_tmd_update_content():
    """Verifies TMD content size and SHA-1 hash recalculation."""
    title_id = b"00010001"
    initial_content = b"APP_CONTENT_INITIAL_DATA_12345"
    sha = hashlib.sha1(initial_content).digest()

    tmd = _build_dummy_tmd(title_id, [(0, 1, len(initial_content), sha)])
    assert tmd.contents[0].size == len(initial_content)
    assert tmd.contents[0].sha1_hash == sha

    # Update content
    new_content = b"APP_CONTENT_MODIFIED_AND_EXPANDED_DATA_67890_LONGER"
    tmd.update_content(0, new_content)
    assert tmd.contents[0].size == len(new_content)
    assert tmd.contents[0].sha1_hash == hashlib.sha1(new_content).digest()

    # Re-reading raw bytes must reflect changes
    parsed_again = WADTmd.from_bytes(tmd.to_bytes())
    assert parsed_again.contents[0].size == len(new_content)
    assert parsed_again.contents[0].sha1_hash == hashlib.sha1(new_content).digest()


def test_wad_container_full_roundtrip_and_u8_bridge():
    """
    Comprehensive test: builds a synthetic WAD containing an in-memory U8Archive,
    verifies full encryption/decryption roundtrip, mutates U8 content, and verifies
    TMD hash updates and Trucha bug fake signing.
    """
    common_key = b"MOCK_COMMON_KEY_"
    title_key = b"MOCK_TITLE_KEY__"
    title_id = b"00010002"

    # Create U8 archive as content 0 (the main .app)
    inner_u8 = U8Archive({"data/dialogue.txt": b"HERO: Let us defeat the demon king!"})
    u8_bytes = inner_u8.to_bytes()

    # Create dummy content 1 (.app extra asset)
    content1_bytes = b"SOUND_EFFECT_DATA_FOR_WII_GAME_AUDIO"

    # Synthesize TMD and Ticket
    c0_sha = hashlib.sha1(u8_bytes).digest()
    c1_sha = hashlib.sha1(content1_bytes).digest()

    tmd = _build_dummy_tmd(
        title_id,
        [
            (0, 1, len(u8_bytes), c0_sha),
            (1, 1, len(content1_bytes), c1_sha),
        ],
    )
    ticket = _build_dummy_ticket(title_id, common_key, title_key)

    wad = WADFile(
        wad_type="Is",
        wad_version=0,
        certs=b"CERT_CHAIN_DATA_01234567890123456789",
        ticket=ticket,
        tmd=tmd,
        title_key=title_key,
    )
    # Set decrypted contents
    wad.set_content(0, u8_bytes)
    wad.set_content(1, content1_bytes)

    # Serialize WAD to bytes
    wad_binary = wad.to_bytes(fake_sign=True)
    assert len(wad_binary) % 64 == 0

    # Parse back with common key
    loaded_wad = WADFile.from_bytes(wad_binary, common_key=common_key)
    assert loaded_wad.wad_type == "Is"
    assert loaded_wad.title_key == title_key

    # Direct U8 bridge: extract in-memory U8 archive
    extracted_u8 = loaded_wad.get_u8_archive(0)
    assert "data/dialogue.txt" in extracted_u8
    assert extracted_u8["data/dialogue.txt"] == b"HERO: Let us defeat the demon king!"

    # Surgically modify dialogue in U8
    extracted_u8["data/dialogue.txt"] = b"HERO: The localized quest begins!"
    loaded_wad.set_u8_archive(0, extracted_u8)

    # Verify content was updated and TMD SHA-1 was recalculated
    updated_u8_bytes = loaded_wad.get_content(0)
    assert loaded_wad.tmd.contents[0].size == len(updated_u8_bytes)
    assert loaded_wad.tmd.contents[0].sha1_hash == hashlib.sha1(updated_u8_bytes).digest()

    # Re-save with Trucha bug fake signing
    reserialized = loaded_wad.to_bytes(fake_sign=True)
    # Verify fake signatures (null RSA signature at 4..260)
    ticket_off = 0x40 + ((len(loaded_wad.certs) + 63) & ~63)
    assert reserialized[ticket_off : ticket_off + 4] == schema.pack(">I", 0x10001)
    assert reserialized[ticket_off + 4 : ticket_off + 260] == b"\x00" * 256


def test_wad_summary_and_diagnostics():
    """Verifies summary string contains Title ID, contents, and diagnostic metrics."""
    common_key = b"COMMON_KEY_TEST1"
    title_key = b"TITLE_KEY_TEST_1"
    title_id = b"00010001"
    c_bytes = b"TEST_APP_DATA"
    sha = hashlib.sha1(c_bytes).digest()

    tmd = _build_dummy_tmd(title_id, [(0, 1, len(c_bytes), sha)])
    ticket = _build_dummy_ticket(title_id, common_key, title_key)

    wad = WADFile(ticket=ticket, tmd=tmd, title_key=title_key)
    wad.set_content(0, c_bytes)

    summary = wad.summary()
    assert "WAD Package" in summary
    assert "Contents: 1 file(s)" in summary
    assert "Title Key Status: Available" in summary


def test_wad_invalid_header_handling():
    """Verifies ParseError on invalid WAD headers."""
    with pytest.raises(ParseError):
        WADFile.from_bytes(b"TOO_SHORT")

    # Wrong header size (not 0x20)
    bad_header = schema.pack(">IHHIIIIII", 0x10, 0, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ParseError):
        WADFile.from_bytes(bad_header)
