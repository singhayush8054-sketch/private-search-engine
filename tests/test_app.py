import tempfile
import unittest
from pathlib import Path

from app import index_directory, search_documents


class SearchEngineTests(unittest.TestCase):
    def test_indexes_and_searches_text_and_markdown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "docs"
            root.mkdir()
            (root / "notes.txt").write_text("A private note about alpine hiking.", encoding="utf-8")
            (root / "guide.md").write_text("# Alpine Guide\nA guide to alpine trails.", encoding="utf-8")
            (root / "ignored.csv").write_text("alpine data", encoding="utf-8")
            db = Path(temp) / "index.sqlite3"

            indexed, skipped = index_directory(root, db)
            results = search_documents("alpine", db)

            self.assertEqual(indexed, 2)
            self.assertEqual(skipped, 0)
            self.assertEqual({item["title"] for item in results}, {"notes", "guide"})
            self.assertTrue(all("source" in item and "excerpt" in item for item in results))

    def test_search_terms_are_combined_and_empty_query_returns_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "docs"
            root.mkdir()
            (root / "one.md").write_text("red apple", encoding="utf-8")
            (root / "two.md").write_text("red berry", encoding="utf-8")
            db = Path(temp) / "index.sqlite3"
            index_directory(root, db)

            self.assertEqual([item["title"] for item in search_documents("red apple", db)], ["one"])
            self.assertEqual(search_documents("   ", db), [])

    def test_oversized_and_invalid_utf8_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "docs"
            root.mkdir()
            (root / "large.txt").write_bytes(b"x" * 1_000_001)
            (root / "binary.md").write_bytes(b"\xff\xfe")
            db = Path(temp) / "index.sqlite3"

            indexed, skipped = index_directory(root, db)
            self.assertEqual((indexed, skipped), (0, 2))


if __name__ == "__main__":
    unittest.main()
