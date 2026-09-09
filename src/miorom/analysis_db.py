"""
miorom.analysis_db
~~~~~~~~~~~~~~~~~~
Persistent analysis database for cross-references, function labels, and
signature matches.

The on-disk format is a portable SQLite database (``*.mioromdb``), so analysis
state survives across runs and can be queried without materializing every
entry in Python first.

Usage:
    db = AnalysisDatabase("game.mioromdb")
    db.set_function_name(0x80003100, "main")
    db.add_signature_match(0x80003100, "memcpy", 0.98)
    db.save()

    db = AnalysisDatabase.load("game.mioromdb")
    for xref in AnalysisDatabase.query_xrefs("game.mioromdb", target=0x80003100):
        print(xref)
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from miorom.result import MioRomResult
from miorom.scanner.xref import XRefEntry, XRefGraph, XRefType


@dataclass
class SignatureMatch(MioRomResult):
    address: int
    name: str
    confidence: float


class AnalysisDatabase:
    """Persistent analysis state: xref graph, function names, signature hits."""

    _SQLITE_MAGIC = b"SQLite format 3\x00"

    def __init__(self, path: Optional[str] = None):
        self.path = path or "analysis.mioromdb"
        self.xref_graph = XRefGraph()
        self.function_names: Dict[int, str] = {}
        self.signature_matches: List[SignatureMatch] = []

    def set_function_name(self, address: int, name: str) -> None:
        self.function_names[address] = name

    def get_function_name(self, address: int) -> str:
        return self.function_names.get(address, f"sub_{address:08X}")

    def add_signature_match(self, address: int, name: str, confidence: float) -> None:
        self.signature_matches.append(SignatureMatch(address, name, confidence))

    def save(self, path: Optional[str] = None) -> str:
        """Save all state into one SQLite database and return its path."""
        target = path or self.path
        parent = Path(target).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True)

        try:
            connection = sqlite3.connect(target)
            with connection:
                connection.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS xrefs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source INTEGER NOT NULL,
                        target INTEGER NOT NULL,
                        xref_type TEXT NOT NULL,
                        context TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_xrefs_source ON xrefs(source);
                    CREATE INDEX IF NOT EXISTS idx_xrefs_target ON xrefs(target);
                    CREATE TABLE IF NOT EXISTS function_names (
                        address INTEGER PRIMARY KEY,
                        name TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS signature_matches (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        address INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        confidence REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_signature_address
                        ON signature_matches(address);
                    """
                )
                connection.execute("DELETE FROM xrefs")
                connection.executemany(
                    "INSERT INTO xrefs(source, target, xref_type, context) VALUES (?, ?, ?, ?)",
                    (
                        (
                            entry.source,
                            entry.target,
                            entry.xref_type.value,
                            entry.context,
                        )
                        for refs in self.xref_graph.backward_refs.values()
                        for entry in refs
                    ),
                )
                connection.execute("DELETE FROM function_names")
                connection.executemany(
                    "INSERT INTO function_names(address, name) VALUES (?, ?)",
                    self.function_names.items(),
                )
                connection.execute("DELETE FROM signature_matches")
                connection.executemany(
                    "INSERT INTO signature_matches(address, name, confidence) VALUES (?, ?, ?)",
                    (
                        (match.address, match.name, match.confidence)
                        for match in self.signature_matches
                    ),
                )
                connection.execute("DELETE FROM schema_version")
                connection.execute("INSERT INTO schema_version(version) VALUES (1)")
        finally:
            if "connection" in locals():
                connection.close()

        return target

    @classmethod
    def load(cls, path: str) -> "AnalysisDatabase":
        """Load a SQLite database; legacy JSON sidecar files remain readable."""
        database = cls(path)
        if not cls._is_sqlite(path):
            database._load_legacy_json(path)
            return database

        connection = sqlite3.connect(path)
        try:
            for source, target, xref_type, context in connection.execute(
                "SELECT source, target, xref_type, context FROM xrefs ORDER BY id"
            ):
                database.xref_graph.add_xref(
                    source=source,
                    target=target,
                    xref_type=XRefType(xref_type),
                    context=context,
                )
            database.function_names.update(
                {
                    address: name
                    for address, name in connection.execute(
                        "SELECT address, name FROM function_names ORDER BY address"
                    )
                }
            )
            database.signature_matches.extend(
                SignatureMatch(address, name, confidence)
                for address, name, confidence in connection.execute(
                    "SELECT address, name, confidence FROM signature_matches ORDER BY id"
                )
            )
        finally:
            connection.close()
        return database

    @staticmethod
    def query_xrefs(
        path: str,
        *,
        source: Optional[int] = None,
        target: Optional[int] = None,
        xref_type: Optional[XRefType] = None,
        limit: Optional[int] = None,
    ) -> Iterator[XRefEntry]:
        """Query xrefs directly from SQLite without loading the whole graph."""
        clauses: List[str] = []
        params: List[Any] = []
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        if target is not None:
            clauses.append("target = ?")
            params.append(target)
        if xref_type is not None:
            clauses.append("xref_type = ?")
            params.append(xref_type.value)
        sql = "SELECT source, target, xref_type, context FROM xrefs"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        connection = sqlite3.connect(path)
        try:
            for row in connection.execute(sql, params):
                yield XRefEntry(
                    source=row[0],
                    target=row[1],
                    xref_type=XRefType(row[2]),
                    context=row[3],
                )
        finally:
            connection.close()

    @staticmethod
    def query_function_names(
        path: str,
        *,
        prefix: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[Tuple[int, str]]:
        """Query function names directly from SQLite without loading all labels."""
        if prefix is None:
            sql = "SELECT address, name FROM function_names ORDER BY address"
            params: Tuple[Any, ...] = ()
        else:
            sql = (
                "SELECT address, name FROM function_names "
                "WHERE name LIKE ? ESCAPE '\\' ORDER BY address"
            )
            escaped = (
                prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            params = (escaped,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)

        connection = sqlite3.connect(path)
        try:
            yield from connection.execute(sql, params)
        finally:
            connection.close()

    @classmethod
    def _is_sqlite(cls, path: str) -> bool:
        try:
            with open(path, "rb") as file_obj:
                return file_obj.read(len(cls._SQLITE_MAGIC)) == cls._SQLITE_MAGIC
        except FileNotFoundError:
            return False

    def _load_legacy_json(self, path: str) -> None:
        """Read the pre-SQLite format: JSON xrefs plus ``.labels`` metadata."""
        try:
            self.xref_graph = XRefGraph.load(path)
        except FileNotFoundError:
            pass

        try:
            with open(path + ".labels", "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except FileNotFoundError:
            return

        for address_text, name in data.get("function_names", {}).items():
            self.function_names[int(address_text, 16)] = name
        self.signature_matches.extend(
            SignatureMatch(**match) for match in data.get("signature_matches", [])
        )
