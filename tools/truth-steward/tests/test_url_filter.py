"""Test the per-source URL filter that replaces the unscoped sitemap dump.

The original behavior dumped the entire site sitemap into the proposer prompt,
creating a topic-drift attractor (the 'Falling Hall' attractor surfaced in
routing-baseline-cycle3-2026-05-04). The fix scopes the URL list per source.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRUTH_STEWARD_DIR = HERE.parent.parent
if str(TRUTH_STEWARD_DIR) not in sys.path:
    sys.path.insert(0, str(TRUTH_STEWARD_DIR))

import importlib.util

PROPOSER_PATH = TRUTH_STEWARD_DIR / "truth-steward" / "run_truth_steward_proposer.py"
spec = importlib.util.spec_from_file_location("rtsp", PROPOSER_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SourceParentPathsTests(unittest.TestCase):
    def test_blog_post_yields_parents_up_to_root(self):
        ctx = {"canonical_url": "https://shanecurry.com/blog/dead-beat/"}
        paths = module._source_parent_paths(ctx)
        self.assertIn("/blog/dead-beat/", paths)
        self.assertIn("/blog/", paths)
        self.assertIn("/", paths)

    def test_lab_toy_yields_parents(self):
        ctx = {"canonical_url": "https://shanecurry.com/lab/toys/phosphor/"}
        paths = module._source_parent_paths(ctx)
        self.assertIn("/lab/toys/phosphor/", paths)
        self.assertIn("/lab/toys/", paths)
        self.assertIn("/lab/", paths)
        self.assertIn("/", paths)

    def test_source_ref_used_when_canonical_absent(self):
        ctx = {"source_ref": "https://shanecurry.com/music/discography/"}
        paths = module._source_parent_paths(ctx)
        self.assertIn("/music/discography/", paths)
        self.assertIn("/music/", paths)

    def test_empty_context_returns_empty(self):
        self.assertEqual(module._source_parent_paths({}), set())


class SiteIndexUrlsForSourceTests(unittest.TestCase):
    """The Falling Hall attractor regression test: sitemap-only artifacts
    must NOT survive the per-source filter when the source doesn't reference
    them."""

    def setUp(self):
        # Sample sitemap content covering generic indices + specific artifacts
        self._original_site_index = module._site_index_urls
        sample_urls = [
            "https://shanecurry.com/",
            "https://shanecurry.com/blog/",
            "https://shanecurry.com/blog/dead-beat/",
            "https://shanecurry.com/blog/phosphor/",
            "https://shanecurry.com/lab/",
            "https://shanecurry.com/lab/toys/",
            "https://shanecurry.com/lab/toys/falling-hall/",
            "https://shanecurry.com/lab/toys/phosphor/",
            "https://shanecurry.com/lab/toys/dead-beat/",
            "https://shanecurry.com/lab/toys/triangle-engines/",
            "https://shanecurry.com/lab/tools/chewgum-dsp/",
            "https://shanecurry.com/music/",
            "https://shanecurry.com/music/discography/",
        ]
        module._site_index_urls = lambda: list(sample_urls)

    def tearDown(self):
        module._site_index_urls = self._original_site_index

    def test_dead_beat_blog_excludes_falling_hall(self):
        ctx = {"canonical_url": "https://shanecurry.com/blog/dead-beat/"}
        result = module._site_index_urls_for_source(ctx)
        self.assertNotIn("https://shanecurry.com/lab/toys/falling-hall/", result,
            "regression: per-source filter should EXCLUDE Falling Hall when proposing for dead-beat blog post")
        self.assertNotIn("https://shanecurry.com/lab/toys/phosphor/", result,
            "regression: per-source filter should EXCLUDE phosphor when proposing for dead-beat")
        self.assertNotIn("https://shanecurry.com/lab/tools/chewgum-dsp/", result,
            "regression: per-source filter should EXCLUDE chewgum-dsp when proposing for dead-beat")

    def test_dead_beat_blog_includes_generic_indices_and_own_path(self):
        ctx = {"canonical_url": "https://shanecurry.com/blog/dead-beat/"}
        result = module._site_index_urls_for_source(ctx)
        self.assertIn("https://shanecurry.com/", result)
        self.assertIn("https://shanecurry.com/blog/", result)
        self.assertIn("https://shanecurry.com/lab/", result)
        self.assertIn("https://shanecurry.com/lab/toys/", result)
        self.assertIn("https://shanecurry.com/blog/dead-beat/", result)

    def test_phosphor_blog_excludes_falling_hall(self):
        ctx = {"canonical_url": "https://shanecurry.com/blog/phosphor/"}
        result = module._site_index_urls_for_source(ctx)
        self.assertNotIn("https://shanecurry.com/lab/toys/falling-hall/", result,
            "regression: per-source filter should EXCLUDE Falling Hall when proposing for phosphor blog post")

    def test_lab_toy_source_keeps_its_own_url(self):
        ctx = {"canonical_url": "https://shanecurry.com/lab/toys/phosphor/"}
        result = module._site_index_urls_for_source(ctx)
        self.assertIn("https://shanecurry.com/lab/toys/phosphor/", result)
        self.assertNotIn("https://shanecurry.com/lab/toys/falling-hall/", result,
            "even when source IS itself a lab toy, should not bring in OTHER lab toys")

    def test_empty_context_yields_empty_list(self):
        result = module._site_index_urls_for_source({})
        # With no source context, only generic indices come through
        self.assertNotIn("https://shanecurry.com/lab/toys/falling-hall/", result)


if __name__ == "__main__":
    unittest.main()
