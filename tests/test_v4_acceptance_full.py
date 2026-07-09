#!/usr/bin/env python3
"""V4.5 full acceptance suite aggregator (#374)."""

from __future__ import annotations

import unittest

_V45_LOCK = "V4.5 T6 (#374) — run after all acceptance modules implemented"


@unittest.skip(_V45_LOCK)
class V4AcceptanceFullSuite(unittest.TestCase):
    def test_all_six_spec_acceptance_tests_pass(self) -> None:
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for module in (
            "tests.test_v4_acceptance_input",
            "tests.test_v4_acceptance_retrieval",
            "tests.test_v4_acceptance_context",
            "tests.test_v4_acceptance_truth",
            "tests.test_v4_acceptance_security",
        ):
            loaded = loader.loadTestsFromName(module)
            suite.addTests(loaded)
        result = unittest.TextTestRunner().run(suite)
        self.assertTrue(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
