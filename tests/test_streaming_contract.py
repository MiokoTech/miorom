from itertools import islice

from miorom.core.scanner import PointerScanner, StringScanner
from miorom.scanner.crypto import CryptoScanner
from miorom.scanner.deep import DeepScanner
from miorom.scanner.pattern import AOBPatternScanner
from miorom.scanner.table_detector import HeuristicTableDetector
from miorom.scanner.triage import RomTriageEngine


def test_streaming_contract(tmp_path):
    data = b"\x00alpha\x00beta\x00gamma\x00"
    strings = StringScanner.iter_strings(data, min_length=4)
    assert next(islice(strings, 1, None)).text == "beta"

    assert len(list(AOBPatternScanner.iter_matches(b"\xaa\x01\xbb\xaa\x02\xbb", "AA ?? BB"))) == 2

    high = bytes(range(256)) * 8
    low = bytes(1024)
    assert list(DeepScanner().iter_compressed_blocks(low + high + low))

    signatures = CryptoScanner.AES_SBOX_PREFIX + b"\x00"
    assert len(list(CryptoScanner.iter_matches(signatures))) == 1

    assert list(HeuristicTableDetector.iter_pointer_tables(data, min_entries=4)) == []

    sample = tmp_path / "sample.bin"
    sample.write_bytes(data)
    records = RomTriageEngine.iter_directory(str(tmp_path))
    assert len(list(records)) == 1

    targets = [0x200, 0x204]
    footer = b"\x00\x00\x02\x00\x04\x00\x02\x00"
    assert list(PointerScanner.iter_footer_pointer_tables(footer, targets, footer_scan_bytes=8)) == []
