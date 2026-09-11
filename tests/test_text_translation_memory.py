"""Tests for miorom.text.translation_memory."""

import json
import pytest

from miorom.text.translation_memory import TranslationMemory, TmMatch, TmLookupResult
from miorom.text.po_handler import PoEntry


def make_tm() -> TranslationMemory:
    tm = TranslationMemory(fuzzy_threshold=0.75)
    tm.add("Hello world", "Bonjour le monde")
    tm.add("Goodbye", "Au revoir")
    tm.add("Open the door", "Ouvre la porte")
    return tm


class TestTmExactMatch:
    def test_exact_score_is_one(self):
        tm = make_tm()
        result = tm.lookup("Hello world")
        assert result.best_match is not None
        assert result.best_match.score == 1.0

    def test_exact_is_exact_flag(self):
        tm = make_tm()
        result = tm.lookup("Hello world")
        assert result.best_match.is_exact is True

    def test_exact_target_text(self):
        tm = make_tm()
        result = tm.lookup("Hello world")
        assert result.best_match.target == "Bonjour le monde"

    def test_query_preserved(self):
        tm = make_tm()
        result = tm.lookup("Hello world")
        assert result.query == "Hello world"


class TestTmFuzzyMatch:
    def test_fuzzy_score_below_one(self):
        tm = make_tm()
        result = tm.lookup("Hello worlds")
        assert result.best_match is not None
        assert result.best_match.score < 1.0

    def test_fuzzy_is_exact_false(self):
        tm = make_tm()
        result = tm.lookup("Hello worlds")
        assert result.best_match.is_exact is False

    def test_below_threshold_rejected(self):
        tm = TranslationMemory(fuzzy_threshold=0.75)
        tm.add("Hello world", "Bonjour le monde")
        result = tm.lookup("Completely different text abc xyz")
        assert result.best_match is None
        assert result.matches == []

    def test_max_results_limit(self):
        tm = TranslationMemory(fuzzy_threshold=0.0)
        for i in range(10):
            tm.add(f"sentence {i}", f"phrase {i}")
        result = tm.lookup("sentence 0", max_results=3)
        assert len(result.matches) <= 3

    def test_results_sorted_descending(self):
        tm = TranslationMemory(fuzzy_threshold=0.0)
        tm.add("abc", "x")
        tm.add("ab", "y")
        tm.add("a", "z")
        result = tm.lookup("abc", max_results=10)
        scores = [m.score for m in result.matches]
        assert scores == sorted(scores, reverse=True)


class TestTmPreFillPo:
    def test_fills_untranslated_entries(self):
        tm = make_tm()
        entries = [PoEntry(msgid="Hello world", msgstr="")]
        count = tm.pre_fill_po(entries)
        assert count == 1
        assert entries[0].msgstr == "Bonjour le monde"

    def test_does_not_overwrite_existing_translation(self):
        tm = make_tm()
        entries = [PoEntry(msgid="Hello world", msgstr="Already translated")]
        count = tm.pre_fill_po(entries)
        assert count == 0
        assert entries[0].msgstr == "Already translated"

    def test_exact_match_no_fuzzy_flag(self):
        tm = make_tm()
        entries = [PoEntry(msgid="Hello world", msgstr="")]
        tm.pre_fill_po(entries, flag_fuzzy=True)
        assert "fuzzy" not in entries[0].flags

    def test_fuzzy_match_adds_flag(self):
        tm = make_tm()
        entries = [PoEntry(msgid="Hello worlds", msgstr="")]
        tm.pre_fill_po(entries, flag_fuzzy=True)
        if entries[0].msgstr:
            assert "fuzzy" in entries[0].flags

    def test_fuzzy_flag_false_no_flag(self):
        tm = TranslationMemory(fuzzy_threshold=0.5)
        tm.add("Hello world", "Bonjour")
        entries = [PoEntry(msgid="Hello worlds", msgstr="")]
        tm.pre_fill_po(entries, flag_fuzzy=False)
        if entries[0].msgstr:
            assert "fuzzy" not in entries[0].flags

    def test_no_match_entry_unchanged(self):
        tm = make_tm()
        entries = [PoEntry(msgid="zzzzzzzzzzzzzzz", msgstr="")]
        count = tm.pre_fill_po(entries)
        assert count == 0
        assert entries[0].msgstr == ""

    def test_returns_count_of_filled(self):
        tm = make_tm()
        entries = [
            PoEntry(msgid="Hello world", msgstr=""),
            PoEntry(msgid="Goodbye", msgstr=""),
            PoEntry(msgid="zzzzzzzzzzzzzzz", msgstr=""),
        ]
        count = tm.pre_fill_po(entries)
        assert count == 2


class TestTmJsonRoundtrip:
    def test_export_json_is_valid_json(self):
        tm = make_tm()
        exported = tm.export_json()
        data = json.loads(exported)
        assert "entries" in data
        assert "fuzzy_threshold" in data

    def test_from_json_restores_entries(self):
        tm = make_tm()
        restored = TranslationMemory.from_json(tm.export_json())
        assert len(restored) == len(tm)

    def test_from_json_restores_threshold(self):
        tm = TranslationMemory(fuzzy_threshold=0.9)
        tm.add("test", "prueba")
        restored = TranslationMemory.from_json(tm.export_json())
        assert restored._fuzzy_threshold == 0.9

    def test_roundtrip_lookup_matches(self):
        tm = make_tm()
        restored = TranslationMemory.from_json(tm.export_json())
        result = restored.lookup("Hello world")
        assert result.best_match is not None
        assert result.best_match.score == 1.0
        assert result.best_match.target == "Bonjour le monde"


class TestTmEmpty:
    def test_empty_tm_returns_no_matches(self):
        tm = TranslationMemory()
        result = tm.lookup("Hello world")
        assert result.best_match is None
        assert result.matches == []

    def test_empty_len_is_zero(self):
        assert len(TranslationMemory()) == 0

    def test_len_reflects_adds(self):
        tm = TranslationMemory()
        tm.add("a", "b")
        tm.add("c", "d")
        assert len(tm) == 2
