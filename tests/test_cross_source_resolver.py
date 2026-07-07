#!/usr/bin/env python3
"""V4 T14 — cross-source resolver and context depth tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import context_resolution  # noqa: E402
import crowley  # noqa: E402
import tickets  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

XSYS_KEY = "XSYS-RESOLVER-TEST"


class CrossSourceResolverTests(unittest.TestCase):
    def test_handoff_dominates_memory_duplicate(self) -> None:
        memories = [
            {
                "id": 2,
                "memory_type": "event",
                "source": "portable_terminal",
                "content": f"Memory signal. Unique phrase: {XSYS_KEY}.",
                "score": 0.86,
                "inclusion_reason": "Pulled because: recent + keyword match",
            },
            {
                "id": 1,
                "memory_type": "project_update",
                "source": "chatgpt",
                "content": f"Handoff signal. Unique phrase: {XSYS_KEY}.",
                "score": 0.95,
                "inclusion_reason": "Pulled because: handoff link + recent + keyword match",
            },
        ]
        resolved, matched, trace = context_resolution.cross_source_resolve(
            memories,
            query=XSYS_KEY,
            depth="medium",
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["id"], 1)
        self.assertTrue(resolved[0]["resolved"])
        self.assertEqual(resolved[0]["dominant_source"], "handoff")
        related = resolved[0]["related_signals"]
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["id"], 2)
        self.assertEqual(related[0]["role"], "suppressed_duplicate")
        self.assertEqual(trace["suppressed_count"], 1)
        self.assertEqual(trace["clusters_formed"], 1)
        self.assertEqual(matched, [])

    def test_ticket_attached_to_cluster(self) -> None:
        memories = [
            {
                "id": 10,
                "memory_type": "project_update",
                "source": "chatgpt",
                "content": f"Handoff for {XSYS_KEY}",
                "score": 0.9,
            }
        ]
        ticket = {
            "id": 99,
            "title": f"QA ticket for {XSYS_KEY}",
            "description": "",
            "status": "open",
        }
        resolved, matched, _trace = context_resolution.cross_source_resolve(
            memories,
            matched_tickets=[ticket],
            query=XSYS_KEY,
            depth="medium",
        )
        self.assertEqual(len(resolved), 1)
        related = resolved[0]["related_signals"]
        self.assertTrue(any(item["kind"] == "ticket" and item["id"] == 99 for item in related))
        self.assertEqual(matched, [])

    def test_unrelated_memories_pass_through(self) -> None:
        memories = [
            {
                "id": 1,
                "memory_type": "event",
                "source": "manual",
                "content": "alpha topic only",
                "score": 0.8,
            },
            {
                "id": 2,
                "memory_type": "event",
                "source": "manual",
                "content": "beta topic only",
                "score": 0.7,
            },
        ]
        resolved, _matched, trace = context_resolution.cross_source_resolve(
            memories,
            query="alpha",
            depth="medium",
        )
        self.assertEqual(len(resolved), 2)
        self.assertFalse(resolved[0]["resolved"])
        self.assertEqual(trace["suppressed_count"], 0)


class ContextBundleDepthTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self._original_embed_text = crowley.embed_text
        crowley.embed_text = lambda _text: None  # type: ignore[assignment]
        self.memory_ids: list[int] = []
        self.ticket_ids: list[int] = []

    def tearDown(self) -> None:
        crowley.embed_text = self._original_embed_text  # type: ignore[assignment]
        for memory_id in self.memory_ids:
            self.conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
        for ticket_id in self.ticket_ids:
            self.conn.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
        self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _insert_memory(
        self,
        *,
        content: str,
        memory_type: str = "event",
        source: str = "manual",
    ) -> int:
        now = crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', 1.0)
            """,
            (
                now,
                now,
                self.project_id,
                memory_type,
                content,
                content[:120],
                3,
                source,
            ),
        )
        self.conn.commit()
        memory_id = int(cur.lastrowid)
        self.memory_ids.append(memory_id)
        return memory_id

    def test_build_context_bundle_resolves_duplicates(self) -> None:
        key = f"{XSYS_KEY}-bundle"
        handoff_id = self._insert_memory(
            content=f"Handoff duplicate test {key}",
            memory_type="project_update",
            source="chatgpt",
        )
        memory_id = self._insert_memory(
            content=f"Memory duplicate test {key}",
            memory_type="event",
            source="portable_terminal",
        )
        bundle = crowley.build_context_bundle(q=key, limit=8, depth="medium")
        memories = bundle["relevant_memories"]
        assert isinstance(memories, list)
        ids = {int(item["id"]) for item in memories}
        self.assertIn(handoff_id, ids)
        self.assertNotIn(memory_id, ids)
        top = next(item for item in memories if int(item["id"]) == handoff_id)
        self.assertTrue(top.get("resolved"))
        trace = bundle.get("trace")
        assert isinstance(trace, dict)
        self.assertIn("clusters_formed", trace)
        self.assertIn("fallback_used", trace)
        self.assertGreaterEqual(int(trace["suppressed_count"]), 1)

    def test_depth_light_has_no_matched_tickets_lane(self) -> None:
        key = f"{XSYS_KEY}-light"
        self._insert_memory(content=f"Light depth probe {key}")
        created = tickets.create_ticket(
            project_id=self.project_id,
            title=f"Ticket for {key}",
            description="",
            status="open",
            assignee="cursor",
            priority=2,
            source="manual",
        )
        self.ticket_ids.append(int(created["ticket"]["id"]))
        bundle = crowley.build_context_bundle(q=key, limit=5, depth="light")
        self.assertEqual(bundle.get("depth"), "light")
        self.assertEqual(bundle.get("matched_tickets"), [])

    def test_legacy_bundle_without_depth_unchanged(self) -> None:
        key = f"{XSYS_KEY}-legacy"
        first = self._insert_memory(content=f"Legacy one {key}")
        second = self._insert_memory(content=f"Legacy two {key}")
        bundle = crowley.build_context_bundle(q=key, limit=8)
        self.assertNotIn("trace", bundle)
        memories = bundle["relevant_memories"]
        assert isinstance(memories, list)
        ids = {int(item["id"]) for item in memories}
        self.assertIn(first, ids)
        self.assertIn(second, ids)


class CognitiveContextDepthTests(IsolatedDbTestCase):
    def test_light_depth_limits_supporting(self) -> None:
        import context_orchestration

        payload = context_orchestration.build_cognitive_context(
            "health",
            depth="light",
            limit=12,
        )
        self.assertEqual(payload["depth"], "light")
        self.assertEqual(payload["supporting_sparks"], [])
        trace = payload["trace"]
        self.assertEqual(trace["depth"], "light")
        self.assertIn("fallback_used", trace)
        self.assertIn("active_spark_count", trace)

    def test_invalid_depth_rejected(self) -> None:
        with self.assertRaises(ValueError):
            context_resolution.normalize_depth("verbose")


if __name__ == "__main__":
    unittest.main()
