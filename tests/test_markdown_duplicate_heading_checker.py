#!/usr/bin/env python3
"""Tests for markdown-duplicate-heading-checker-cli.

Standard library only. Run from the repo root:

    python3 tests/test_markdown_duplicate_heading_checker.py
"""

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "markdown_duplicate_heading_checker.py"
sys.path.insert(0, str(ROOT / "src"))

import markdown_duplicate_heading_checker as checker  # noqa: E402

BANNED_WORDS = ["TODO", "FIXME", "coming soon", "lorem"]


def run_cli(*args, stdin_text=None, cwd=None):
    """Run the checker as a real command. Returns (exit, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, str(SRC), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=cwd or str(ROOT),
    )
    return result.returncode, result.stdout, result.stderr


def write_tmp(tmpdir, name, content):
    """Write content to a file under tmpdir, return its path string."""
    path = Path(tmpdir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestHeadingParsing(unittest.TestCase):
    """ATX and setext heading parsing."""

    def headings(self, text):
        return checker.find_headings(text)

    def test_atx_levels_one_to_six(self):
        found = self.headings("# One\n## Two\n### Three\n#### Four\n##### Five\n###### Six\n")
        self.assertEqual([h.level for h in found], [1, 2, 3, 4, 5, 6])
        self.assertEqual([h.text for h in found], ["One", "Two", "Three", "Four", "Five", "Six"])
        self.assertEqual([h.lineno for h in found], [1, 2, 3, 4, 5, 6])

    def test_seven_hashes_is_not_a_heading(self):
        self.assertEqual(self.headings("####### Seven\n"), [])

    def test_no_space_after_hashes_is_not_a_heading(self):
        self.assertEqual(self.headings("##NoSpace\n"), [])

    def test_four_leading_spaces_is_not_a_heading(self):
        self.assertEqual(self.headings("    ## Indented\n"), [])

    def test_three_leading_spaces_is_a_heading(self):
        found = self.headings("   ## Indented\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].level, 2)

    def test_closing_hashes_stripped(self):
        found = self.headings("## Setup ##\n")
        self.assertEqual(found[0].text, "Setup")

    def test_bare_hashes_are_not_headings(self):
        self.assertEqual(self.headings("##\n## \n"), [])

    def test_trailing_spaces_ignored(self):
        dups = checker.find_duplicates(self.headings("## Setup   \n\n## Setup\n"))
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["lines"], [1, 3])

    def test_case_insensitive_match(self):
        dups = checker.find_duplicates(self.headings("## Setup\n\n## setup\n"))
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["text"], "Setup")

    def test_whitespace_collapse_match(self):
        dups = checker.find_duplicates(
            self.headings("## Setup  Guide\n\n## Setup Guide\n")
        )
        self.assertEqual(len(dups), 1)

    def test_setext_level_one(self):
        found = self.headings("Title\n=====\n")
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].level, found[0].text), (1, "Title"))

    def test_setext_level_two(self):
        found = self.headings("Guide\n-----\n")
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].level, found[0].text), (2, "Guide"))

    def test_setext_after_blank_line_is_not_a_heading(self):
        self.assertEqual(self.headings("Guide\n\n-----\n"), [])

    def test_list_item_is_not_setext_text(self):
        self.assertEqual(self.headings("- item\n---\n"), [])

    def test_blockquote_is_not_setext_text(self):
        self.assertEqual(self.headings("> quoted\n---\n"), [])

    def test_thematic_break_after_paragraph_is_not_a_heading(self):
        self.assertEqual(self.headings("Some text\n\n***\n"), [])

    def test_fenced_code_block_ignored(self):
        found = self.headings("# Real\n\n```\n## Fake\n```\n\n## Real Two\n")
        self.assertEqual([h.text for h in found], ["Real", "Real Two"])

    def test_tilde_fence_ignored(self):
        found = self.headings("~~~\n## Fake\n~~~\n\n## Real\n")
        self.assertEqual([h.text for h in found], ["Real"])

    def test_fence_with_info_string_ignored(self):
        found = self.headings("```markdown\n## Fake\n```\n\n## Real\n")
        self.assertEqual([h.text for h in found], ["Real"])

    def test_unclosed_fence_ignores_rest(self):
        found = self.headings("## Before\n\n```\n## Inside\n")
        self.assertEqual([h.text for h in found], ["Before"])

    def test_front_matter_skipped(self):
        text = "---\ntitle: Guide\n---\n\n# Guide\n"
        found = self.headings(text)
        self.assertEqual([h.text for h in found], ["Guide"])
        self.assertEqual(found[0].lineno, 5)

    def test_front_matter_title_not_a_setext_heading(self):
        text = "---\ntitle: Guide\n---\n\nSome text\n"
        self.assertEqual(self.headings(text), [])

    def test_empty_document(self):
        self.assertEqual(self.headings(""), [])
        self.assertEqual(self.headings("\n\n"), [])


class TestDuplicateFinding(unittest.TestCase):
    """Duplicate grouping rules."""

    def test_same_text_same_level_is_a_duplicate(self):
        dups = checker.find_duplicates(
            checker.find_headings("## Setup\n\n## Setup\n")
        )
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["text"], "Setup")
        self.assertEqual(dups[0]["level"], 2)
        self.assertEqual(dups[0]["lines"], [1, 3])

    def test_same_text_different_levels_is_not_a_duplicate(self):
        dups = checker.find_duplicates(
            checker.find_headings("## Setup\n\n### Setup\n")
        )
        self.assertEqual(dups, [])

    def test_three_occurrences_all_listed(self):
        dups = checker.find_duplicates(
            checker.find_headings("## A\n\n## A\n\n## A\n")
        )
        self.assertEqual(dups[0]["lines"], [1, 3, 5])

    def test_two_groups_in_first_seen_order(self):
        dups = checker.find_duplicates(
            checker.find_headings("## B\n\n## A\n\n## B\n\n## A\n")
        )
        self.assertEqual([d["text"] for d in dups], ["B", "A"])

    def test_setext_and_atx_same_level_match(self):
        dups = checker.find_duplicates(
            checker.find_headings("Guide\n-----\n\n## Guide\n")
        )
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["level"], 2)

    def test_clean_file_has_no_duplicates(self):
        dups = checker.find_duplicates(
            checker.find_headings("# Guide\n\n## Setup\n\n## Install\n")
        )
        self.assertEqual(dups, [])


class TestCli(unittest.TestCase):
    """End-to-end CLI behaviour."""

    def test_clean_file_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "good.md", "# Guide\n\n## Setup\n")
            code, out, _ = run_cli(path)
            self.assertEqual(code, 0)
            self.assertEqual(
                out, "OK — 1 file(s) checked, no duplicate headings found.\n"
            )

    def test_duplicate_file_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "bad.md", "## Setup\n\n## Setup\n")
            code, out, _ = run_cli(path)
            self.assertEqual(code, 1)
            self.assertIn('duplicate heading "Setup" (level 2) at lines 1, 3', out)
            self.assertIn("Checked 1 file(s), 1 problem(s) in 1 file(s).", out)

    def test_same_heading_in_two_files_is_not_a_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = write_tmp(tmp, "a.md", "## Setup\n")
            second = write_tmp(tmp, "b.md", "## Setup\n")
            code, out, _ = run_cli(first, second)
            self.assertEqual(code, 0)
            self.assertIn("OK — 2 file(s) checked", out)

    def test_missing_path_exit_two(self):
        code, _, err = run_cli("no-such-file.md")
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_no_args_exit_two(self):
        code, _, err = run_cli()
        self.assertEqual(code, 2)
        self.assertIn("no files or folders given", err)

    def test_bad_flag_exit_two(self):
        code, _, _ = run_cli("--nope")
        self.assertEqual(code, 2)

    def test_folder_walk_checks_markdown_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tmp(tmp, "a.md", "## Setup\n\n## Setup\n")
            write_tmp(tmp, "b.txt", "## Setup\n\n## Setup\n")
            write_tmp(tmp, "c.markdown", "## Clean\n")
            code, out, _ = run_cli(tmp)
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)
            self.assertNotIn("b.txt", out)

    def test_git_folder_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tmp(tmp, ".git/hooks/a.md", "## Setup\n\n## Setup\n")
            write_tmp(tmp, "a.md", "## Clean\n")
            code, out, _ = run_cli(tmp)
            self.assertEqual(code, 0)
            self.assertIn("OK — 1 file(s) checked", out)

    def test_no_recursive_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tmp(tmp, "a.md", "## Clean\n")
            write_tmp(tmp, "sub/b.md", "## Setup\n\n## Setup\n")
            code, out, _ = run_cli("--no-recursive", tmp)
            self.assertEqual(code, 0)
            self.assertIn("OK — 1 file(s) checked", out)
            code, out, _ = run_cli(tmp)
            self.assertEqual(code, 1)
            self.assertIn("Checked 2 file(s)", out)

    def test_exclude_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_tmp(tmp, "a.md", "## Setup\n\n## Setup\n")
            write_tmp(tmp, "b.md", "## Setup\n\n## Setup\n")
            code, out, _ = run_cli("--exclude", "b.md", tmp)
            self.assertEqual(code, 1)
            self.assertIn("Checked 1 file(s)", out)

    def test_direct_file_any_name_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "notes.txt", "## Setup\n\n## Setup\n")
            code, out, _ = run_cli(path)
            self.assertEqual(code, 1)
            self.assertIn("notes.txt", out)

    def test_same_file_twice_checked_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "a.md", "## Clean\n")
            code, out, _ = run_cli(path, path)
            self.assertEqual(code, 0)
            self.assertIn("OK — 1 file(s) checked", out)

    def test_empty_folder_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_cli(tmp)
            self.assertEqual(code, 2)
            self.assertIn("no Markdown files found", err)

    def test_stdin_clean_and_dirty(self):
        code, out, _ = run_cli("--stdin", stdin_text="# Guide\n\n## Setup\n")
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 file(s) checked", out)
        code, out, _ = run_cli("--stdin", stdin_text="## Setup\n\n## Setup\n")
        self.assertEqual(code, 1)
        self.assertIn('FAIL <stdin>: duplicate heading "Setup"', out)

    def test_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "bad.md", "## Setup\n\n## Setup\n")
            code, out, _ = run_cli("--json", path)
            self.assertEqual(code, 1)
            report = json.loads(out)
            self.assertEqual(report["checked"], 1)
            self.assertEqual(report["problems"], 1)
            self.assertEqual(report["files"][0]["duplicates"][0]["text"], "Setup")
            self.assertEqual(report["files"][0]["duplicates"][0]["lines"], [1, 3])
            self.assertIsNone(report["files"][0]["error"])

    def test_non_utf8_file_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.md"
            path.write_bytes(b"## Setup\n\n\xff\xfe bad bytes\n")
            code, out, _ = run_cli(str(path))
            self.assertEqual(code, 1)
            self.assertIn("cannot read file", out)

    def test_version_flag(self):
        code, out, _ = run_cli("--version")
        self.assertEqual(code, 0)
        self.assertIn("1.0.0", out)

    def test_input_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tmp(tmp, "a.md", "## Setup\n\n## Setup\n")
            before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            run_cli(path)
            after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            self.assertEqual(before, after)


class TestBundledExamples(unittest.TestCase):
    """The examples/ folder behaves exactly as the README says."""

    def test_good_example_passes(self):
        code, out, _ = run_cli(str(ROOT / "examples" / "good.md"))
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 file(s) checked", out)

    def test_duplicates_example_fails(self):
        code, out, _ = run_cli(str(ROOT / "examples" / "duplicates.md"))
        self.assertEqual(code, 1)
        self.assertIn('duplicate heading "Setup" (level 2) at lines 3, 11, 15', out)

    def test_code_block_example_passes(self):
        code, out, _ = run_cli(str(ROOT / "examples" / "code-block.md"))
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 file(s) checked", out)

    def test_subfolder_example_fails(self):
        code, out, _ = run_cli(str(ROOT / "examples" / "configs" / "guide.md"))
        self.assertEqual(code, 1)
        self.assertIn('duplicate heading "Options" (level 2) at lines 3, 7', out)

    def test_run_example_output_matches_sample(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0)
        saved = (ROOT / "examples" / "sample-output.md").read_text(encoding="utf-8")
        self.assertEqual(result.stdout, saved)

    def test_repo_own_docs_are_clean(self):
        code, out, _ = run_cli(
            str(ROOT / "README.md"),
            str(ROOT / "CONTRIBUTING.md"),
            str(ROOT / "SECURITY.md"),
        )
        self.assertEqual(code, 0)
        self.assertIn("OK — 3 file(s) checked", out)


class TestReadmeQuotes(unittest.TestCase):
    """Every command quoted in the README gives the quoted output."""

    def quoted_commands_and_outputs(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        commands = re.findall(r"```sh\n\$ ([^\n]+)\n```", readme)
        outputs = re.findall(r"```text\n(.*?)```", readme, re.DOTALL)
        return commands, outputs

    def test_text_blocks_match_live_output(self):
        commands, outputs = self.quoted_commands_and_outputs()
        self.assertEqual(len(commands), 6)
        self.assertEqual(len(outputs), 5)
        text_commands = [c for c in commands if "--json" not in c]
        self.assertEqual(len(text_commands), 5)
        for command, expected in zip(text_commands, outputs):
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            self.assertEqual(
                result.stdout.strip(),
                expected.strip(),
                "README output differs for: {0}".format(command),
            )

    def test_json_block_matches_live_output(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```json\n(.*?)```", readme, re.DOTALL)
        self.assertEqual(len(blocks), 1)
        result = subprocess.run(
            "python3 src/markdown_duplicate_heading_checker.py --json "
            "examples/duplicates.md",
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(result.stdout.strip(), blocks[0].strip())
        json.loads(blocks[0])


class TestHygiene(unittest.TestCase):
    """No placeholders, no secrets, stdlib only, template rules."""

    def repo_files(self):
        found = []
        for path in ROOT.rglob("*"):
            if path.is_file():
                parts = path.relative_to(ROOT).parts
                if parts[0] in (".git", "__pycache__"):
                    continue
                if "__pycache__" in parts:
                    continue
                found.append(path)
        return found

    def test_no_banned_words_outside_tests(self):
        for path in self.repo_files():
            if "tests" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for word in BANNED_WORDS:
                self.assertNotIn(
                    word, text, "{0} contains {1!r}".format(path, word)
                )

    def test_no_absolute_paths(self):
        home = str(Path.home())
        for path in self.repo_files():
            if "tests" in path.relative_to(ROOT).parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn(home, text, "{0} contains a home path".format(path))

    def test_stdlib_imports_only(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        allowed = set(sys.stdlib_module_names)
        self.assertTrue(
            imported <= allowed,
            "non-stdlib imports: {0}".format(sorted(imported - allowed)),
        )
        self.assertNotIn("yaml", imported)

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_the_test_file(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("tests/test_markdown_duplicate_heading_checker.py", ci)
        self.assertIn("setup-python", ci)


if __name__ == "__main__":
    unittest.main(verbosity=2)
