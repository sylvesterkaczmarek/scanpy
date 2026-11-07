"""Prepare and test a targeted backport without creating an upstream PR."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = Path(os.environ["REVIEW_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
TEST = ROOT / "tests/test_combat_categorical.py"
SOURCE = ROOT / "src/scanpy/preprocessing/_combat.py"
NOTE = ROOT / "docs/release-notes/+combat-categorical-backport.fix.md"
BASE = "f044749be194031efa0087988b544dd59a19630b"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == BASE
assert not subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
assert not TEST.exists() and not NOTE.exists()
shutil.copyfile(Path(__file__).with_name("test_combat_categorical.py"), TEST)
subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", str(TEST)], check=True)
subprocess.run([sys.executable, "-m", "ruff", "format", str(TEST)], check=True)
old = SOURCE.read_text()
fragment = 'f"~ 0 + {col_repr}", model[other_cols], return_type="dataframe"\n        )'
replacement = 'f"~ {col_repr}", model[other_cols], return_type="dataframe"\n        ).drop(columns="Intercept")'
assert old.count(fragment) == 1
runs = []


def run(label, paths):
    xml = OUT / f"{label}.xml"
    command = [sys.executable, "-m", "pytest", *paths, "-q", f"--junitxml={xml}"]
    with (OUT / f"{label}.log").open("w") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
    print((OUT / f"{label}.log").read_text(), flush=True)
    node = ET.parse(xml).getroot()
    counts = {key: sum(int(s.get(key, 0)) for s in node.iter("testsuite"))
              for key in ("tests", "failures", "errors", "skipped")}
    record = {"label": label, "command": command, "exit_code": result.returncode, **counts}
    runs.append(record)
    return record


red = run("original", [str(TEST)])
assert red["exit_code"] == 1 and red["failures"] >= 2 and red["errors"] == 0, red
SOURCE.write_text(old.replace(fragment, replacement))
NOTE.write_text(
    "Backport the categorical-covariate reference coding from PR #4389 to the "
    "1.12 maintenance branch, avoiding a redundant column in "
    "{func}`scanpy.pp.combat` design matrices (issue #4454).\n"
)
green = run("fixed", ["tests/test_combat.py", str(TEST)])
assert green["exit_code"] == 0 and green["skipped"] == 0, green
subprocess.run([sys.executable, "-m", "ruff", "check", str(TEST)], check=True)
subprocess.run([sys.executable, "-m", "ruff", "format", "--check", str(TEST)], check=True)
subprocess.run(["git", "diff", "--check"], check=True)
files = [str(p.relative_to(ROOT)) for p in [SOURCE, TEST, NOTE]]
for name in files:
    target = OUT / "files" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / name, target)
summary = {"base": BASE, "issue": 4454, "files": files, "runs": runs,
           "source_hashes": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files},
           "scope": "ComBat tests on the 1.12 maintenance branch; no patient data or full-suite claim",
           "upstream_pr_submitted": False}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
subprocess.run(["git", "add", "--", *files], check=True)
(OUT / "patch.diff").write_bytes(subprocess.check_output(["git", "diff", "--cached", "--binary"]))
assert sorted(subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()) == sorted(files)
print("VALIDATED", json.dumps(summary), flush=True)
