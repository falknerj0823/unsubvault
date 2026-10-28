"""Check the Markdown docs: every relative link points at a file that exists, and the docs index lists every doc.

    python scripts/check_docs.py"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
files = [*ROOT.glob("docs/**/*.md"), *ROOT.glob("*.md")]
errors = []
for f in files:
    for m in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", f.read_text()):
        target = m.group(1)
        if re.match(r"^(https?:|mailto:)", target):
            continue
        if not (f.parent / target).resolve().exists():
            errors.append(f"{f.relative_to(ROOT)}: broken link to {target}")
index = (ROOT / "docs" / "README.md").read_text()
for f in (ROOT / "docs").glob("**/*.md"):
    rel = f.relative_to(ROOT / "docs").as_posix()
    if rel != "README.md" and rel not in index:
        errors.append(f"docs/README.md does not list {rel}")
for e in errors:
    print("ERROR:", e)
print(f"{len(files)} markdown files checked, {len(errors)} problem(s)")
sys.exit(1 if errors else 0)
