"""Golden tests. Every tests/fixtures/<name>.diff is paired with <name>.expected.jsonl."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
BUNDLED = ROOT / "rules.yml"
# Fixtures that need a project's rules on top of the bundled ones.
EXTRA_RULES = {"api": [FIXTURES / "sorl-thumbnail.yml"]}

DIFF = b"""\
diff --git a/.gitignore b/.gitignore
--- a/.gitignore
+++ b/.gitignore
@@ -0,0 +1 @@
+.venv/
diff --git a/tests/fixtures/x.diff b/tests/fixtures/x.diff
--- a/tests/fixtures/x.diff
+++ b/tests/fixtures/x.diff
@@ -0,0 +1 @@
+hello
"""


def check(diff, *rules):
    command = [sys.executable, "-I", str(ROOT / "pr-hygiene.py"), *map(str, rules)]
    return subprocess.run(command, input=diff, capture_output=True, check=False)


def hits(result):
    assert result.stderr == b""
    return [line.split(", ")[0] for line in result.stdout.decode().splitlines()]


def rules_file(tmp_path, text):
    path = tmp_path / "rules.yml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("name", sorted(path.stem for path in FIXTURES.glob("*.diff")))
def test_fixture(name):
    diff = (FIXTURES / f"{name}.diff").read_bytes()
    expected = (FIXTURES / f"{name}.expected.jsonl").read_text(encoding="utf-8")
    result = check(diff, BUNDLED, *EXTRA_RULES.get(name, []))
    assert result.stderr == b""
    assert result.stdout.decode() == expected
    assert result.returncode == (1 if expected else 0)


def test_bundled_rules_alone():
    assert hits(check(DIFF, BUNDLED)) == ['{"path": "tests/fixtures/x.diff"']


def test_later_file_adds_rules(tmp_path):
    extra = rules_file(
        tmp_path,
        """
        rules:
          - name: gitignore
            severity: cleanup
            paths: [".gitignore"]
            message: Leave it.
        """,
    )
    assert hits(check(DIFF, BUNDLED, extra)) == [
        '{"path": ".gitignore"',
        '{"path": "tests/fixtures/x.diff"',
    ]


def test_same_name_replaces_rule(tmp_path):
    extra = rules_file(
        tmp_path,
        """
        rules:
          - name: scratch-files
            severity: hold
            paths: ["*.diff"]
            message: Diffs need a look.
        """,
    )
    result = check(DIFF, BUNDLED, extra)
    assert result.stderr == b""
    assert '"severity": "hold", "message": "Diffs need a look."' in result.stdout.decode()


def test_most_severe_rule_wins_whatever_the_order(tmp_path):
    rules = rules_file(
        tmp_path,
        """
        rules:
          - name: first
            severity: cleanup
            paths: ["*.diff"]
            message: Listed first.
          - name: second
            severity: block
            paths: ["tests/**"]
            message: Listed second.
        """,
    )
    result = check(DIFF, rules)
    assert result.stderr == b""
    assert '"rule": "second", "severity": "block"' in result.stdout.decode()


def test_enabled_false_drops_rule(tmp_path):
    extra = rules_file(tmp_path, "rules:\n  - name: scratch-files\n    enabled: false\n")
    result = check(DIFF, BUNDLED, extra)
    assert result.stderr == b""
    assert result.stdout == b""
    assert result.returncode == 0


def test_exclude_skips_paths(tmp_path):
    extra = rules_file(tmp_path, 'exclude: ["tests/fixtures/**"]\n')
    result = check(DIFF, BUNDLED, extra)
    assert result.stderr == b""
    assert result.stdout == b""
    assert result.returncode == 0


def test_unknown_severity_fails(tmp_path):
    bad = rules_file(
        tmp_path, "rules:\n  - {name: x, severity: urgent, paths: ['*'], message: m}\n"
    )
    result = check(DIFF, bad)
    assert result.returncode == 1
    assert result.stdout == b""
    assert b"rule x has unknown severity urgent" in result.stderr


def test_missing_key_fails(tmp_path):
    bad = rules_file(tmp_path, "rules:\n  - {name: x, severity: hold, paths: ['*']}\n")
    result = check(DIFF, bad)
    assert result.returncode == 1
    assert b"rule x needs message" in result.stderr


def test_no_rules_file_prints_usage():
    result = check(DIFF)
    assert result.returncode == 1
    assert b"Usage:" in result.stderr


def test_repo_has_no_invisible_characters():
    """The invisible-characters rule must never fire on this repository's own files."""
    rules = yaml.safe_load(BUNDLED.read_text(encoding="utf-8"))["rules"]
    pattern = re.compile(next(r["content"] for r in rules if r["name"] == "invisible-characters"))
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout
    for name in listing.decode().split("\0"):
        if not name or name.startswith("tests/fixtures/"):
            continue
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        assert not pattern.search(text), f"{name} contains invisible characters"
