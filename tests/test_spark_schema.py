#!/usr/bin/env python3
"""V4 T1/T2 — sparks, spark_links, and patterns schema tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

_REQUIRED_NO_DEFAULT = frozenset({
    "content",
    "lane",
    "why_keep",
    "worth_reason",
    "trust_state",
    "created_at",
})
_REQUIRED_WITH_DEFAULT = frozenset({
    "confidence",
    "base_confidence",
    "sensitivity",
    "access_count",
    "content_encrypted",
    "updated_at",
})
_OPTIONAL_NULLABLE = frozenset({
    "tags_json",
    "source_refs_json",
    "lineage_json",
    "owner_id",
    "source_memory_item_id",
    "last_accessed_at",
    "project_id",
    "embedding_blob",
    "embed_model",
    "embed_dim",
})
_ALL_COLUMNS = (
    _REQUIRED_NO_DEFAULT
    | _REQUIRED_WITH_DEFAULT
    | _OPTIONAL_NULLABLE
    | {"id"}
)


def _column_info(
    conn: sqlite3.Connection,
    table: str,
) -> dict[str, dict[str, object]]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {
        str(row[1]): {
            "notnull": int(row[3]),
            "dflt_value": row[4],
        }
        for row in rows
    }


_SPARK_LINKS_REQUIRED_NO_DEFAULT = frozenset({
    "from_spark_id",
    "to_spark_id",
    "link_type",
    "created_at",
})
_SPARK_LINKS_REQUIRED_WITH_DEFAULT = frozenset({
    "confidence",
    "updated_at",
})
_SPARK_LINKS_ALL_COLUMNS = _SPARK_LINKS_REQUIRED_NO_DEFAULT | _SPARK_LINKS_REQUIRED_WITH_DEFAULT | {"id"}

_PATTERNS_REQUIRED_NO_DEFAULT = frozenset({
    "content",
    "lane",
    "reasoning",
    "trust_state",
    "created_at",
})
_PATTERNS_REQUIRED_WITH_DEFAULT = frozenset({
    "confidence",
    "updated_at",
})
_PATTERNS_OPTIONAL_NULLABLE = frozenset({"source_spark_ids_json"})
_PATTERNS_ALL_COLUMNS = (
    _PATTERNS_REQUIRED_NO_DEFAULT
    | _PATTERNS_REQUIRED_WITH_DEFAULT
    | _PATTERNS_OPTIONAL_NULLABLE
    | {"id"}
)


def _minimal_spark_values(*, include_timestamps: bool = True) -> dict[str, object]:
    values: dict[str, object] = {
        "content": "Crowley V4 spark schema landed.",
        "lane": "work",
        "why_keep": "Documents T1 schema foundation.",
        "worth_reason": "Unblocks spark_links and validation tickets.",
        "trust_state": "candidate",
    }
    if include_timestamps:
        now = crowley._now_iso()
        values["created_at"] = now
        values["updated_at"] = now
    return values


def _insert_spark(
    conn: sqlite3.Connection,
    *,
    content: str = "Seed spark for graph schema tests.",
) -> int:
    values = _minimal_spark_values()
    values["content"] = content
    cur = conn.execute(
        """
        INSERT INTO sparks (
            content, lane, why_keep, worth_reason, trust_state,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            values["content"],
            values["lane"],
            values["why_keep"],
            values["worth_reason"],
            values["trust_state"],
            values["created_at"],
            values["updated_at"],
        ),
    )
    return int(cur.lastrowid)


class SparkSchemaTests(IsolatedDbTestCase):
    def test_sparks_table_exists(self) -> None:
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sparks'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)

    def test_sparks_column_nullability(self) -> None:
        conn = crowley.connect_db()
        try:
            info = _column_info(conn, "sparks")
        finally:
            conn.close()

        self.assertEqual(set(info), _ALL_COLUMNS)

        for name in _REQUIRED_NO_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNone(info[name]["dflt_value"], name)

        for name in _REQUIRED_WITH_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNotNone(info[name]["dflt_value"], name)

        for name in _OPTIONAL_NULLABLE:
            self.assertEqual(info[name]["notnull"], 0, name)
            self.assertIsNone(info[name]["dflt_value"], name)

    def test_spark_lanes_match_portable_writeback(self) -> None:
        self.assertEqual(sparks.SPARK_LANES, frozenset(crowley.PORTABLE_WRITEBACK_LANES))

    def test_spark_trust_states_and_sensitivities(self) -> None:
        self.assertEqual(
            sparks.SPARK_TRUST_STATES,
            frozenset({"candidate", "active", "stale", "pinned", "rejected"}),
        )
        self.assertEqual(
            sparks.SPARK_SENSITIVITIES,
            frozenset(crowley.PORTABLE_WRITEBACK_SENSITIVITIES),
        )
        self.assertEqual(sparks.SPARK_CONTENT_MAX_LEN, 300)

    def test_valid_spark_insert(self) -> None:
        conn = crowley.connect_db()
        try:
            values = _minimal_spark_values()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sparks WHERE id = last_insert_rowid()").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["content"], values["content"])
        self.assertEqual(row["lane"], "work")
        self.assertEqual(row["confidence"], 0.5)
        self.assertEqual(row["base_confidence"], 0.5)
        self.assertEqual(row["sensitivity"], "normal")
        self.assertIsNone(row["tags_json"])

    def test_invalid_spark_insert_missing_required(self) -> None:
        conn = crowley.connect_db()
        try:
            now = crowley._now_iso()
            with self.assertRaises(crowley.sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO sparks (
                        content, lane, worth_reason, trust_state,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("missing why_keep", "work", "reason", "candidate", now, now),
                )
        finally:
            conn.close()

    def test_optional_json_fields_nullable(self) -> None:
        conn = crowley.connect_db()
        try:
            values = _minimal_spark_values()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state,
                    tags_json, source_refs_json, lineage_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            conn.commit()
            row = conn.execute("SELECT tags_json FROM sparks WHERE id = last_insert_rowid()").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNone(row["tags_json"])

    def test_confidence_default_on_omit(self) -> None:
        conn = crowley.connect_db()
        try:
            values = _minimal_spark_values()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT confidence, base_confidence FROM sparks WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["confidence"], 0.5)
        self.assertEqual(row["base_confidence"], 0.5)

    def test_confidence_explicit_override(self) -> None:
        conn = crowley.connect_db()
        try:
            values = _minimal_spark_values()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state,
                    confidence, base_confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    0.8,
                    0.8,
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT confidence, base_confidence FROM sparks WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["confidence"], 0.8)
        self.assertEqual(row["base_confidence"], 0.8)

    def test_updated_at_default_on_omit(self) -> None:
        conn = crowley.connect_db()
        try:
            values = _minimal_spark_values(include_timestamps=False)
            created_at = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    created_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT updated_at FROM sparks WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(str(row["updated_at"]).strip())

    def test_spark_fk_to_memory_item(self) -> None:
        conn = crowley.connect_db()
        try:
            project_id = crowley._active_project_id(conn)
            assert project_id is not None
            now = crowley._now_iso()
            memory_id = crowley.save_memory_item(
                "event",
                "source memory for spark lineage",
                source="cursor",
                project_id=project_id,
                conn=conn,
            )
            assert memory_id is not None
            values = _minimal_spark_values()
            conn.execute(
                """
                INSERT INTO sparks (
                    content, lane, why_keep, worth_reason, trust_state,
                    source_memory_item_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["content"],
                    values["lane"],
                    values["why_keep"],
                    values["worth_reason"],
                    values["trust_state"],
                    memory_id,
                    values["created_at"],
                    values["updated_at"],
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT source_memory_item_id FROM sparks WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["source_memory_item_id"], memory_id)


class SparkLinksSchemaTests(IsolatedDbTestCase):
    def test_spark_links_table_exists(self) -> None:
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'spark_links'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)

    def test_spark_links_column_nullability(self) -> None:
        conn = crowley.connect_db()
        try:
            info = _column_info(conn, "spark_links")
        finally:
            conn.close()

        self.assertEqual(set(info), _SPARK_LINKS_ALL_COLUMNS)

        for name in _SPARK_LINKS_REQUIRED_NO_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNone(info[name]["dflt_value"], name)

        for name in _SPARK_LINKS_REQUIRED_WITH_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNotNone(info[name]["dflt_value"], name)

    def test_spark_link_valid_insert(self) -> None:
        conn = crowley.connect_db()
        try:
            from_id = _insert_spark(conn, content="Link source spark.")
            to_id = _insert_spark(conn, content="Link target spark.")
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO spark_links (
                    from_spark_id, to_spark_id, link_type, confidence,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (from_id, to_id, "reinforces", 0.7, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM spark_links WHERE id = last_insert_rowid()").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["from_spark_id"], from_id)
        self.assertEqual(row["to_spark_id"], to_id)
        self.assertEqual(row["link_type"], "reinforces")
        self.assertEqual(row["confidence"], 0.7)

    def test_spark_link_invalid_fk(self) -> None:
        conn = crowley.connect_db()
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            spark_id = _insert_spark(conn)
            now = crowley._now_iso()
            with self.assertRaises(crowley.sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO spark_links (
                        from_spark_id, to_spark_id, link_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (spark_id, 999_999, "reinforces", now, now),
                )
        finally:
            conn.close()

    def test_spark_link_confidence_default(self) -> None:
        conn = crowley.connect_db()
        try:
            from_id = _insert_spark(conn, content="Default confidence source.")
            to_id = _insert_spark(conn, content="Default confidence target.")
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO spark_links (
                    from_spark_id, to_spark_id, link_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (from_id, to_id, "reinforces", now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT confidence FROM spark_links WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["confidence"], 0.5)

    def test_spark_link_updated_at_default_on_omit(self) -> None:
        conn = crowley.connect_db()
        try:
            from_id = _insert_spark(conn, content="Updated-at default source.")
            to_id = _insert_spark(conn, content="Updated-at default target.")
            created_at = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO spark_links (
                    from_spark_id, to_spark_id, link_type, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (from_id, to_id, "reinforces", created_at),
            )
            conn.commit()
            row = conn.execute(
                "SELECT updated_at FROM spark_links WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(str(row["updated_at"]).strip())

    def test_self_link_allowed(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_spark(conn, content="Self-link spark.")
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO spark_links (
                    from_spark_id, to_spark_id, link_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (spark_id, spark_id, "reinforces", now, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT from_spark_id, to_spark_id FROM spark_links WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["from_spark_id"], spark_id)
        self.assertEqual(row["to_spark_id"], spark_id)


class PatternsSchemaTests(IsolatedDbTestCase):
    def test_patterns_table_exists(self) -> None:
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'patterns'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)

    def test_patterns_column_nullability(self) -> None:
        conn = crowley.connect_db()
        try:
            info = _column_info(conn, "patterns")
        finally:
            conn.close()

        self.assertEqual(set(info), _PATTERNS_ALL_COLUMNS)

        for name in _PATTERNS_REQUIRED_NO_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNone(info[name]["dflt_value"], name)

        for name in _PATTERNS_REQUIRED_WITH_DEFAULT:
            self.assertEqual(info[name]["notnull"], 1, name)
            self.assertIsNotNone(info[name]["dflt_value"], name)

        for name in _PATTERNS_OPTIONAL_NULLABLE:
            self.assertEqual(info[name]["notnull"], 0, name)
            self.assertIsNone(info[name]["dflt_value"], name)

    def test_pattern_valid_insert(self) -> None:
        conn = crowley.connect_db()
        try:
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO patterns (
                    content, lane, reasoning, trust_state,
                    source_spark_ids_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    "Repeated focus on schema-first delivery.",
                    "operating_style",
                    "Three work-lane sparks cluster on disciplined planning.",
                    "candidate",
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM patterns WHERE id = last_insert_rowid()").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["lane"], "operating_style")
        self.assertEqual(row["confidence"], 0.5)
        self.assertIsNone(row["source_spark_ids_json"])

    def test_pattern_invalid_missing_reasoning(self) -> None:
        conn = crowley.connect_db()
        try:
            now = crowley._now_iso()
            with self.assertRaises(crowley.sqlite3.IntegrityError):
                conn.execute(
                    """
                    INSERT INTO patterns (
                        content, lane, trust_state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    ("Pattern without reasoning.", "work", "candidate", now, now),
                )
        finally:
            conn.close()

    def test_pattern_updated_at_default_on_omit(self) -> None:
        conn = crowley.connect_db()
        try:
            created_at = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO patterns (
                    content, lane, reasoning, trust_state, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Pattern updated_at fallback.",
                    "work",
                    "Documents updated_at default behavior.",
                    "candidate",
                    created_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT updated_at FROM patterns WHERE id = last_insert_rowid()"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(str(row["updated_at"]).strip())


if __name__ == "__main__":
    unittest.main()
