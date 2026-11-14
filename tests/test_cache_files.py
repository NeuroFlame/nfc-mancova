"""Cover the author-facing, run-scoped cache filename helper."""

import os
import unittest

from framework import cache_file


class CacheFileTests(unittest.TestCase):
    def test_named_path_is_stable(self):
        self.assertEqual(
            cache_file("statistics.npy", cache_dir="/cache"),
            os.path.join("/cache", "statistics.npy"),
        )

    def test_unsafe_names_are_rejected(self):
        for name in ("", ".", "..", "../x", "/x", "sub/x", "sub\\x", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cache_file(name, cache_dir="/cache")

    def test_missing_cache_directory_is_rejected(self):
        for directory in (None, ""):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                cache_file("statistics.npy", cache_dir=directory)
