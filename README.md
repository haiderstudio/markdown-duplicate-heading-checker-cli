# markdown-duplicate-heading-checker-cli

Find duplicate headings in Markdown, fail CI when a heading repeats.

[![CI](https://github.com/haiderstudio/markdown-duplicate-heading-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/markdown-duplicate-heading-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`markdown_duplicate_heading_checker` reads Markdown files and
finds every heading text that appears twice at the same level in
one file — two `## Setup` sections, for example — and reports
each one with the file, the level, and every line number. It
exits 1 when any duplicate is found, so it can fail a CI run.
A file with no repeated headings exits 0.

- Two sections with the same heading break anchor links: a
  `#setup` link always jumps to the first one, and a reader
  cannot tell the two sections apart. This tool catches that
  before the doc ships, instead of after a reader gets lost.
- Headings match case-insensitively and ignore extra spacing:
  `## Setup` and `## setup` are the same heading, and so are
  `## Setup  Guide` and `## Setup Guide`. Trailing spaces and
  closing hashes (`## Setup ##`) do not matter.
- Same text at a different level is NOT a duplicate: `## Setup`
  and `### Setup` are different sections and both pass.
- ATX headings (`#` to `######`) and setext headings (text
  underlined with `===` for level 1 or `---` for level 2) both
  count. A heading inside a fenced code block does **not**
  count, and neither does a YAML front-matter block at the top
  of the file.
- A file given directly on the command line is always checked,
  whatever its name. A folder is walked for Markdown files
  (`.md` and `.markdown`), recursively by default
  (`--no-recursive` stops at the top level). `.git` folders
  are never walked, and directory links are never followed.
- `--json` prints the result as JSON (the human-readable lines
  go to standard error), and `--stdin` checks one document
  read from standard input.

## Who it is for

Anyone who writes docs, READMEs, or blog posts in Markdown and
wants every heading to be unique — open-source maintainers,
teams that review each other's docs, and anyone who has ever
clicked an anchor link and landed on the wrong section.

## What it does NOT do

- It does not check heading *order* — that is Day 27's
  heading-order-checker-cli. This tool checks repeats only.
- It does not check whether anchor links point at a heading
  that exists. A duplicate heading is the problem it finds;
  a missing anchor target is a different check.
- It does not check the *quality* of a heading — a vague
  heading passes, as long as it appears once. Writing a good
  heading is still the author's job.
- It does not check any other file type, and it never rewrites
  a file. It is report-only, and it never touches the network.

## How this differs

- winnielinnie/doc-ship-check (0 stars) is a final-pass
  Markdown checker for placeholders, broken links, AND
  duplicate headings — duplicate headings are one check among
  three, its own sample output reports a duplicate heading
  with no line number, and the repo has no CI workflow. This
  tool is duplicate-headings-only, reports every line number
  for every repeat, walks folders, and ships a CI workflow
  that fails the build on a duplicate.
- Day 27's heading-order-checker-cli checks heading order;
  duplicates are a different job on the same files.

## Install

```sh
git clone https://github.com/haiderstudio/markdown-duplicate-heading-checker-cli.git
cd markdown-duplicate-heading-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies.

## Usage

Check one file:

```sh
python3 src/markdown_duplicate_heading_checker.py README.md
```

A clean file passes:

```sh
$ python3 src/markdown_duplicate_heading_checker.py examples/good.md
```

```text
OK — 1 file(s) checked, no duplicate headings found.
```

A file with a repeated heading fails:

```sh
$ python3 src/markdown_duplicate_heading_checker.py examples/duplicates.md
```

```text
FAIL examples/duplicates.md: duplicate heading "Setup" (level 2) at lines 3, 11, 15
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Check a whole folder (Markdown files only):

```sh
python3 src/markdown_duplicate_heading_checker.py docs/
```

Check one document from standard input:

```sh
$ python3 src/markdown_duplicate_heading_checker.py --stdin < examples/duplicates.md
```

```text
FAIL <stdin>: duplicate heading "Setup" (level 2) at lines 3, 11, 15
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Machine-readable output:

```sh
$ python3 src/markdown_duplicate_heading_checker.py --json examples/duplicates.md
```

```json
{
  "files": [
    {
      "path": "examples/duplicates.md",
      "duplicates": [
        {
          "text": "Setup",
          "level": 2,
          "lines": [
            3,
            11,
            15
          ]
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "problems": 1
}
```

Exit codes: 0 when no file checked has a duplicate heading,
1 when any duplicate is found or a file cannot be read, 2 for
a usage error (a missing path, a bad flag, or no Markdown
files found).

## Examples

A heading inside a fenced code block does not count — only
the one real `## Setup` is seen, so the file passes:

```sh
$ python3 src/markdown_duplicate_heading_checker.py examples/code-block.md
```

```text
OK — 1 file(s) checked, no duplicate headings found.
```

A whole folder, including a file in a subfolder:

```sh
$ python3 src/markdown_duplicate_heading_checker.py examples/
```

```text
FAIL examples/configs/guide.md: duplicate heading "Options" (level 2) at lines 3, 7
FAIL examples/duplicates.md: duplicate heading "Setup" (level 2) at lines 3, 11, 15
Checked 5 file(s), 2 problem(s) in 2 file(s).
```

The folder run counts `examples/sample-output.md` too, so it
checks 5 files. Run every bundled example at once with `sh
examples/run-example.sh` — the output is saved in
[examples/sample-output.md](examples/sample-output.md).

## How it is tested

```sh
python3 tests/test_markdown_duplicate_heading_checker.py
```

The tests cover heading parsing (ATX headings at every level,
closing hashes stripped, no-space and seven-hash lines never
counted, setext headings at both levels, headings inside
fenced code blocks ignored, YAML front matter skipped, list
items and blockquotes never counted as setext headings,
trailing spaces and case ignored), the duplicate rule (same
text same level fails, same text different levels passes,
three occurrences all listed, groups in first-seen order),
the CLI (exit 0/1/2, folder walking, Markdown files only,
`.git` skipped, `--no-recursive`, `--exclude`, a direct file
checked even without a `.md` name, same file twice checked
once, `--stdin`, `--json` output, `--version`, bad flags,
missing paths, empty folders, a non-UTF-8 file reported,
input files left unchanged), the bundled examples (sample
output compared byte-for-byte against a fresh run, the
repo's own docs checked clean, and the README-quoted outputs
checked against live runs), and hygiene checks (no
placeholder text, no absolute paths, stdlib imports only,
`.env` first in `.gitignore`, CI file runs the test file).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea
of checking Markdown headings is not new — the similar tool
named above (the 0-star doc-ship-check) is listed in "How
this differs" — but every line of code here is original, and
the tool builds on nothing but Python's standard library.
