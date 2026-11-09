#!/bin/sh
# Run the checker over each example file and over the whole examples
# folder, and show the result. Bad examples fail on purpose, so each
# run is allowed to fail.
cd "$(dirname "$0")/.."
for f in examples/good.md examples/duplicates.md examples/code-block.md examples/configs/guide.md; do
  echo "== $f =="
  python3 src/markdown_duplicate_heading_checker.py "$f" || true
  echo
done
echo "== examples/ : the whole folder =="
python3 src/markdown_duplicate_heading_checker.py examples/ || true
