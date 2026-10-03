"""Exercise actual Markdown parsing and temporary filesystem fixtures."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from doclink_local.cli import main
from doclink_local.core import DoclinkError, check_documents


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("README.md", "")

    def write(self, name, text=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def check(self, text, **options):
        self.write("README.md", text)
        return check_documents(self.root, ["README.md"], **options)

    def test_relative_links_images_and_directories(self):
        self.write("docs/guide.md")
        self.write("assets/logo.svg")
        report = self.check("[guide](docs/guide.md) ![logo](assets/logo.svg) [dir](docs/)")
        self.assertTrue(report["ok"])
        self.assertEqual(report["local_links_checked"], 3)

    def test_missing_target_reports_block_start(self):
        report = self.check("Title\n\nFirst line\n[next](absent.md)\n")
        self.assertEqual(report["issues"], [{"source": "README.md", "block_line": 3,
                                            "url": "absent.md", "code": "missing"}])

    def test_reference_links_and_collapsed_references(self):
        self.write("guide.md")
        report = self.check("[Guide][doc] [Guide][]\n\n[doc]: guide.md\n[Guide]: guide.md\n")
        self.assertTrue(report["ok"])
        self.assertEqual(report["local_links_checked"], 2)

    def test_undefined_reference_is_not_a_link(self):
        report = self.check("[missing][undefined]")
        self.assertEqual(report["local_links_checked"], 0)

    def test_code_fences_indented_code_and_inline_code_are_ignored(self):
        tick = chr(96)
        report = self.check(f"{tick}[fake](no.md){tick}\n\n{tick * 3}md\n[x](no.md)\n"
                            f"{tick * 3}\n\n    [y](no.md)\n")
        self.assertEqual(report["local_links_checked"], 0)

    def test_nested_labels_parentheses_spaces_and_unicode(self):
        self.write("nested(file).md")
        self.write("with space.md")
        self.write("中文.md")
        report = self.check("[**nested**](nested(file).md) [space](<with space.md>) [語](中文.md)")
        self.assertTrue(report["ok"])
        self.assertEqual(report["local_links_checked"], 3)

    def test_percent_encoding_query_and_fragments(self):
        self.write("with space.md")
        report = self.check("[x](with%20space.md?download=1#not-checked) [self](#heading)")
        self.assertTrue(report["ok"])
        self.assertEqual(report["local_links_checked"], 1)
        self.assertEqual(report["fragments_skipped"], 1)

    def test_external_urls_never_use_sockets(self):
        with patch.object(socket, "socket", side_effect=AssertionError("Network used")):
            report = self.check("[a](https://example.test/x) [b](mailto:x@example.test) "
                                "[c](//cdn.example.test/image) [d](custom:thing)")
        self.assertTrue(report["ok"])
        self.assertEqual(report["external_links_skipped"], 4)

    def test_root_relative_links_require_opt_in(self):
        self.write("guide.md")
        text = "[x](/guide.md) [bad](/missing.md)"
        default = self.check(text)
        self.assertTrue(default["ok"])
        self.assertEqual(default["root_relative_skipped"], 2)
        opted = self.check(text, root_relative=True)
        self.assertEqual(opted["issues_total"], 1)

    def test_parent_path_within_root_is_valid(self):
        self.write("guide.md")
        self.write("docs/index.md", "[x](../guide.md)")
        report = check_documents(self.root, ["docs/index.md"])
        self.assertTrue(report["ok"])

    def test_outside_root_and_encoded_traversal(self):
        report = self.check("[x](../outside.md) [y](%2e%2e/outside.md)")
        self.assertEqual([i["code"] for i in report["issues"]], ["outside_root", "outside_root"])

    def test_absolute_file_uri_is_a_portability_issue(self):
        report = self.check("[x](file:///tmp/private.md)")
        self.assertEqual(report["issues"][0]["code"], "absolute_local")

    def test_html_attributes_tables_and_comments(self):
        self.write("ok.png")
        report = self.check('<img src="ok.png"><video poster="missing.png"></video>\n'
                            '<!-- <a href="comment.md">x</a> -->\n\n'
                            '| Value |\n| --- |\n| [table](missing.md) |\n')
        self.assertEqual(report["local_links_checked"], 3)
        self.assertEqual(report["issues_total"], 2)

    def test_invalid_decoded_paths(self):
        report = self.check('[x](bad%00name.md) [y](folder%5Cfile.md) [z](%FF.md)')
        self.assertEqual([i["code"] for i in report["issues"]],
                         ["invalid_path", "invalid_path", "invalid_url"])

    def test_scan_prunes_generated_directories_and_globs(self):
        self.write("docs/good.md", "[x](../README.md)")
        self.write("node_modules/no.md", "[bad](missing)")
        self.write(".git/no.md", "[bad](missing)")
        self.write("docs/draft.md", "[bad](missing)")
        report = check_documents(self.root, excludes=["docs/draft.md"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["files_scanned"], 2)

    def test_issue_cap_preserves_totals(self):
        report = self.check("[a](a) [b](b) [c](c)", max_issues=1)
        self.assertEqual(report["issues_total"], 3)
        self.assertEqual(len(report["issues"]), 1)
        self.assertTrue(report["issues_truncated"])

    def test_byte_limit_utf8_bom_and_bad_encoding(self):
        self.write("README.md", "long document")
        with self.assertRaises(DoclinkError):
            check_documents(self.root, max_bytes=2)
        (self.root / "README.md").write_bytes(b"\xef\xbb\xbf# Good\n")
        self.assertTrue(check_documents(self.root)["ok"])
        (self.root / "README.md").write_bytes(b"\xff")
        with self.assertRaisesRegex(DoclinkError, "UTF-8"):
            check_documents(self.root)

    def test_selection_boundary_missing_inputs_and_no_documents(self):
        with self.assertRaises(DoclinkError):
            check_documents(self.root, ["../outside.md"])
        with self.assertRaises(DoclinkError):
            check_documents(self.root, ["missing.md"])
        self.write("empty/.keep")
        with self.assertRaisesRegex(DoclinkError, "No Markdown"):
            check_documents(self.root, ["empty"])
        with self.assertRaises(DoclinkError):
            check_documents(self.root, ["empty/.keep"])

    def test_symlink_escape_is_reported_when_supported(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "target.md"
            outside.write_text("", encoding="utf-8")
            try:
                (self.root / "link.md").symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("Host does not allow creating symlinks")
            report = self.check("[x](link.md)")
            self.assertEqual(report["issues"][0]["code"], "outside_root")
            with self.assertRaises(DoclinkError):
                check_documents(self.root)

    def test_cli_json_exit_codes_and_operational_errors(self):
        self.write("README.md", "[x](missing.md)")
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = main(["--root", str(self.root), "--format", "json"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["issues_total"], 1)
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            status = main(["--root", str(self.root), "missing.md"])
        self.assertEqual(status, 2)
        self.write("README.md", "# Good")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--root", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
