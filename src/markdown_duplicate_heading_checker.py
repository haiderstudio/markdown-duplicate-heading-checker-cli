#!/usr/bin/env python3
"""Find duplicate headings in Markdown files.

A heading that appears twice at the same level in one file breaks
anchor links (``#setup`` always jumps to the first one) and confuses
readers. This tool reports every repeated heading with its file,
level, and line numbers, and exits 1 when any duplicate is found,
so it can fail a CI run. Report-only: it never rewrites a file.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

VERSION = "1.0.0"
MARKDOWN_EXTENSIONS = {".md", ".markdown"}

ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*))?$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([*_-])([ \t]*\1){2,}[ \t]*$")
FRONT_MATTER_FENCE_RE = re.compile(r"^(---|\.\.\.)[ \t]*$")
LIST_OR_QUOTE_RE = re.compile(r"^ {0,3}(>|\*|\+|-|\d+[.)])[ \t]")


class Heading:
    """One heading found in a file."""

    def __init__(self, level, text, lineno):
        self.level = level
        self.text = text
        self.lineno = lineno

    @property
    def key(self):
        """Match key: same level, same text ignoring case and spacing."""
        return (self.level, " ".join(self.text.split()).lower())


def normalize_display(text):
    """Collapse runs of whitespace to one space, strip the ends."""
    return " ".join(text.split())


def strip_closing_hashes(text):
    """Remove an ATX closing sequence (``## Setup ##`` -> ``Setup``)."""
    return re.sub(r"[ \t]+#+[ \t]*$", "", text).strip()


def find_headings(content):
    """Return every heading in one Markdown document, in order.

    ATX headings (``#`` to ``######``) and setext headings (text
    underlined with ``===`` for level 1 or ``---`` for level 2).
    Headings inside fenced code blocks are ignored, as is a YAML
    front-matter block at the top of the file.
    """
    headings = []
    lines = content.split("\n")
    in_fence = None
    in_front_matter = False
    front_matter_checked = False
    prev = None
    for index, raw in enumerate(lines):
        lineno = index + 1
        line = raw[:-1] if raw.endswith("\r") else raw
        if not front_matter_checked:
            front_matter_checked = True
            if FRONT_MATTER_FENCE_RE.match(line):
                in_front_matter = True
                continue
        if in_front_matter:
            if FRONT_MATTER_FENCE_RE.match(line):
                in_front_matter = False
            prev = None
            continue
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            char, length = marker[0], len(marker)
            if in_fence is None:
                in_fence = (char, length)
            elif char == in_fence[0] and length >= in_fence[1]:
                in_fence = None
            prev = None
            continue
        if in_fence is not None:
            prev = None
            continue
        if line.strip() == "":
            prev = None
            continue
        atx = ATX_RE.match(line)
        if atx:
            text = strip_closing_hashes(atx.group(2) or "")
            if normalize_display(text):
                headings.append(Heading(len(atx.group(1)), text, lineno))
            prev = None
            continue
        setext = SETEXT_UNDERLINE_RE.match(line)
        if setext and prev is not None:
            level = 1 if setext.group(1).startswith("=") else 2
            text, text_lineno = prev
            if normalize_display(text):
                headings.append(Heading(level, text, text_lineno))
            prev = None
            continue
        if (
            re.match(r"^ {4,}", line)
            or LIST_OR_QUOTE_RE.match(line)
            or SETEXT_UNDERLINE_RE.match(line)
            or THEMATIC_BREAK_RE.match(line)
        ):
            prev = None
        else:
            prev = (line.strip(), lineno)
    return headings


def find_duplicates(headings):
    """Group repeated headings: same level, same text, one file.

    Returns a list of dicts with the heading text, level, and every
    line number, in first-seen order.
    """
    seen = {}
    order = []
    for heading in headings:
        key = heading.key
        if key not in seen:
            seen[key] = {
                "text": normalize_display(heading.text),
                "level": heading.level,
                "lines": [],
            }
            order.append(key)
        seen[key]["lines"].append(heading.lineno)
    return [seen[key] for key in order if len(seen[key]["lines"]) > 1]


def check_text(content, path):
    """Check one document's text. Returns (duplicates, error)."""
    try:
        headings = find_headings(content)
    except Exception as exc:  # pragma: no cover - defensive
        return [], "cannot parse file: {0}".format(exc)
    return find_duplicates(headings), None


def check_file(path):
    """Check one file. Returns (duplicates, error)."""
    try:
        content = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], "cannot read file: {0}".format(exc)
    return check_text(content, path)


def is_markdown(path):
    """True for files this tool walks in a folder."""
    return Path(path).suffix.lower() in MARKDOWN_EXTENSIONS


def collect_files(paths, recursive, excludes):
    """Expand files and folders into a sorted, deduplicated file list."""
    found = []
    seen = set()
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                found.append(str(path))
        elif path.is_dir():
            for root, dirs, files in os.walk(path, topdown=True):
                dirs[:] = [
                    d
                    for d in dirs
                    if d != ".git" and not Path(root, d).is_symlink()
                ]
                if not recursive:
                    dirs[:] = []
                for name in sorted(files):
                    candidate = Path(root, name)
                    if not is_markdown(candidate):
                        continue
                    if any(
                        fnmatch.fnmatch(name, pattern)
                        or fnmatch.fnmatch(str(candidate), pattern)
                        for pattern in excludes
                    ):
                        continue
                    key = str(candidate.resolve())
                    if key not in seen:
                        seen.add(key)
                        found.append(str(candidate))
        else:
            return None, "no such file or folder: {0}".format(raw)
    found.sort()
    return found, None


def check_stdin():
    """Check one document read from standard input."""
    content = sys.stdin.read()
    duplicates, error = check_text(content, "<stdin>")
    return [{"path": "<stdin>", "duplicates": duplicates, "error": error}]


def main(argv=None):
    """Entry point. Exit 0 clean, 1 duplicates found, 2 usage error."""
    parser = argparse.ArgumentParser(
        prog="markdown_duplicate_heading_checker",
        description=(
            "Find duplicate headings in Markdown files. A heading "
            "that appears twice at the same level in one file is "
            "reported with its file, level, and line numbers. "
            "Exits 1 when any duplicate is found, 0 when clean."
        ),
    )
    parser.add_argument(
        "paths", nargs="*", help="Markdown files or folders to check"
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="do not walk into subfolders of a folder given on the command line",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="skip files whose name or path matches this glob (repeatable)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON on standard output",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="check one Markdown document read from standard input",
    )
    parser.add_argument(
        "--version", action="version", version="%(prog)s " + VERSION
    )
    args = parser.parse_args(argv)

    if args.stdin:
        results = check_stdin()
    else:
        if not args.paths:
            parser.error("no files or folders given")
        files, error = collect_files(
            args.paths, not args.no_recursive, args.exclude
        )
        if error is not None:
            print("error: {0}".format(error), file=sys.stderr)
            return 2
        if not files:
            print("error: no Markdown files found", file=sys.stderr)
            return 2
        results = []
        for path in files:
            duplicates, error = check_file(path)
            results.append(
                {"path": path, "duplicates": duplicates, "error": error}
            )

    checked = len(results)
    problems = sum(
        len(item["duplicates"]) + (1 if item["error"] else 0)
        for item in results
    )
    files_with_problems = sum(
        1
        for item in results
        if item["duplicates"] or item["error"]
    )

    if args.json:
        report = {
            "files": results,
            "checked": checked,
            "problems": problems,
        }
        print(json.dumps(report, indent=2))
        return 1 if problems else 0

    for item in results:
        for duplicate in item["duplicates"]:
            lines = ", ".join(str(n) for n in duplicate["lines"])
            print(
                'FAIL {0}: duplicate heading "{1}" (level {2}) '
                "at lines {3}".format(
                    item["path"],
                    duplicate["text"],
                    duplicate["level"],
                    lines,
                )
            )
        if item["error"]:
            print("FAIL {0}: {1}".format(item["path"], item["error"]))
    if problems:
        print(
            "Checked {0} file(s), {1} problem(s) in {2} file(s).".format(
                checked, problems, files_with_problems
            )
        )
        return 1
    print(
        "OK — {0} file(s) checked, no duplicate headings found.".format(
            checked
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
