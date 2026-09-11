import os
import struct
import tempfile
import pytest

from miorom import (
    ROM,
    Game,
    Rule,
    SmartInspector,
    InspectionReport,
    ProjectScaffold,
    TocArchive,
    DualTableDialogue,
    register_codec,
    get_codec,
    register_container,
    get_container,
    register_game,
    get_game,
)


def test_smart_inspector_text_and_entropy():
    # Synthetic binary with English text
    text_data = b"Hello, brave warrior! Welcome to the fantasy kingdom.\x00" * 5
    report = SmartInspector.inspect(text_data)
    assert report.size == len(text_data)
    assert report.overall_entropy < 6.0
    assert report.best_encoding is not None
    assert report.best_encoding.string_count > 0


def test_rom_fluent_api():
    sample = b"Introduction\x00Warrior\x00Mage\x00Attack\x00Defense\x00Magic\x00"
    rom = ROM.from_bytes(sample, name="TestROM")
    assert rom.size == len(sample)
    assert len(rom) == len(sample)

    # String filtering
    results = rom.strings.filter(contains="warrior")
    assert len(results) == 1
    assert "Warrior" in results[0].text

    # Slicing
    sliced = rom.slice(0, 12)
    assert sliced.size == 12

    # Diagnosis
    diag = rom.diagnose()
    assert isinstance(diag, InspectionReport)
    assert "SMART BINARY INSPECTION REPORT" in diag.summary()


def test_rule_textbox_and_tagmap():
    tb = Rule.Textbox(max_chars=10, max_lines=2)
    valid, warnings = tb.validate("Short line")
    assert valid is True

    valid_overflow, warnings = tb.validate("This is a very long line that exceeds limit")
    assert valid_overflow is False
    assert len(warnings) > 0

    tm = Rule.TagMap({"[0xff20]": "<WARNA>", "[PLAYER]": "<HERO>"})
    applied = tm.apply("Hello [PLAYER] [0xff20]Red")
    assert applied == "Hello <HERO> <WARNA>Red"
    reverted = tm.revert(applied)
    assert reverted == "Hello [PLAYER] [0xff20]Red"


def test_game_project_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create dummy text file
        txt_file = os.path.join(tmpdir, "dialog.bin")
        raw_text = "Welcome to our village!\x00Are you an adventurer?\x00".encode("utf-16-be")
        with open(txt_file, "wb") as f:
            f.write(raw_text)

        class TestRPG(Game):
            name = "test_rpg"
            platform = "wii"
            title = "Test RPG"
            dialogues = [DualTableDialogue(txt_file, encoding="utf-16-be", id="village_dialog")]
            rules = [Rule.Textbox(max_chars=40, max_lines=3)]

        game = TestRPG()

        # Analyze
        game.analyze()

        # Extract
        out_dir = os.path.join(tmpdir, "translations")
        extracted = game.extract(output_dir=out_dir)
        assert "village_dialog" in extracted
        assert os.path.exists(extracted["village_dialog"])

        # Validate
        is_valid = game.validate(translations_dir=out_dir)
        assert is_valid is True

        # Build
        game.build(output_rom=os.path.join(tmpdir, "build.iso"))


def test_scaffold_generator():
    with tempfile.TemporaryDirectory() as tmpdir:
        proj_dir = os.path.join(tmpdir, "my_mod")
        res = ProjectScaffold.generate("my_mod", dest_dir=proj_dir, platform="wii")
        assert os.path.exists(os.path.join(proj_dir, "game.py"))
        assert os.path.exists(os.path.join(proj_dir, "miorom.yaml"))
        for d in ["original", "extracted", "translations", "build", "patches"]:
            assert os.path.isdir(os.path.join(proj_dir, d))


def test_registry_plugins():
    @register_codec("custom_lz42")
    class DummyCodec:
        pass

    @register_container("custom_pac")
    class DummyContainer:
        pass

    @register_game("custom_rpg")
    class DummyGame(Game):
        pass

    assert get_codec("custom_lz42") is DummyCodec
    assert get_container("custom_pac") is DummyContainer
    assert get_game("custom_rpg") is DummyGame
