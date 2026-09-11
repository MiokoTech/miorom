import os
import struct
import tempfile
import pytest

from miorom.cli.main import main


def test_cli_scan_text(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "sample.bin")
        sjis_bytes = "勇者の伝説".encode("shift_jis") + b"\x00"
        with open(test_file, "wb") as f:
            f.write(b"\xFF\xFF" + sjis_bytes + b"\x00\x00")

        monkeypatch.setattr("sys.argv", ["miorom", "scan-text", test_file, "-e", "sjis"])
        main()
        captured = capsys.readouterr()
        assert "[*] Scanning binary text streams" in captured.out
        assert "勇者の伝説" in captured.out


def test_cli_disasm(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "code.bin")
        # 68000 NOP (4E71), RTS (4E75)
        with open(test_file, "wb") as f:
            f.write(bytes([0x4E, 0x71, 0x4E, 0x75]))

        monkeypatch.setattr("sys.argv", ["miorom", "disasm", test_file, "-a", "m68k", "-n", "2"])
        main()
        captured = capsys.readouterr()
        assert "[*] Disassembling" in captured.out
        assert "NOP" in captured.out
        assert "RTS" in captured.out


def test_cli_checksum(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "rom.bin")
        # 512 bytes dummy ROM
        data = bytearray(b"\x00" * 512)
        with open(test_file, "wb") as f:
            f.write(data)

        monkeypatch.setattr("sys.argv", ["miorom", "checksum", test_file, "-s", "all"])
        main()
        captured = capsys.readouterr()
        assert "[*] Analyzing checksum" in captured.out
        assert "CRC-32" in captured.out
        assert "Genesis Sum" in captured.out


def test_cli_reloc_branch(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "branch.bin")
        out_file = os.path.join(tmpdir, "branch_reloc.bin")
        # 6502 BEQ +4 from orig_pc 0x8000
        with open(test_file, "wb") as f:
            f.write(bytes([0xF0, 0x04]))

        monkeypatch.setattr(
            "sys.argv",
            [
                "miorom",
                "reloc-branch",
                test_file,
                "-a",
                "6502",
                "--orig-base",
                "0x8000",
                "--new-base",
                "0x9000",
                "-o",
                out_file,
            ],
        )
        main()
        captured = capsys.readouterr()
        assert "[*] Rebasing relative branches" in captured.out
        assert "[✓] Saved rebased binary" in captured.out
        assert os.path.isfile(out_file)


def test_cli_tile_dedup(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "tiles.bin")
        out_file = os.path.join(tmpdir, "tiles.opt")
        # 2 identical 2bpp tiles (32 bytes)
        with open(test_file, "wb") as f:
            f.write(bytes([0xAA, 0x55] * 8) * 2)

        monkeypatch.setattr(
            "sys.argv",
            ["miorom", "tile-dedup", test_file, "--bpp", "2", "-o", out_file],
        )
        main()
        captured = capsys.readouterr()
        assert "[*] Optimizing and deduplicating 8x8 tiles" in captured.out
        assert "[✓] Saved deduplicated tiles" in captured.out
        assert os.path.isfile(out_file)
        assert os.path.getsize(out_file) == 16
