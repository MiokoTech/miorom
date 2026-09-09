import pytest

from miorom.errors import (
    MioromError,
    ParseError,
    ChecksumError,
    RelocationError,
    UnsupportedFormatError,
)


def test_all_exceptions_inherit_from_miorom_error():
    for exc in (ParseError, ChecksumError, RelocationError, UnsupportedFormatError):
        assert issubclass(exc, MioromError)


def test_miorom_error_inherits_from_exception():
    assert issubclass(MioromError, Exception)


def test_message_preserved_through_hierarchy():
    with pytest.raises(MioromError, match="bad magic"):
        raise ParseError("bad magic at 0x00")


def test_catch_specific_not_base():
    with pytest.raises(ChecksumError):
        raise ChecksumError("CIC mismatch")
    with pytest.raises(MioromError):
        raise ChecksumError("CIC mismatch")
