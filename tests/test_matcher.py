"""Golden tests. Every tests/fixtures/<name>.diff is paired with <name>.expected.jsonl."""

import os
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


@pytest.fixture(autouse=True)
def repo(tmp_path, monkeypatch):
    """Run the matcher in an empty repository, so this one's .gitignore never counts."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


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


IGNORED_RULE = """
rules:
  - name: ignored-files
    severity: hold
    paths: ["*"]
    ignored: true
    message: Ignored.
"""


def added(*paths):
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -0,0 +1 @@\n+x\n" for p in paths
    ).encode()


def base_branch(repo, files, force=()):
    """Write files into the repository and track them, force-adding the ones in force."""
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", *files.keys() - set(force)], cwd=repo, check=True)
    if force:
        subprocess.run(["git", "add", "-f", *force], cwd=repo, check=True)


def test_ignored_fires_on_added_ignored_files(repo, tmp_path):
    base_branch(repo, {".gitignore": "CLAUDE.md\n.claude/\n", "docs/.gitignore": "*.log\n"})
    diff = added("CLAUDE.md", "src/CLAUDE.md", ".claude/settings.json", "docs/a.log", "a.log")
    assert hits(check(diff, rules_file(tmp_path, IGNORED_RULE))) == [
        '{"path": "CLAUDE.md"',
        '{"path": "src/CLAUDE.md"',
        '{"path": ".claude/settings.json"',
        '{"path": "docs/a.log"',
    ]


def test_ignored_uses_the_base_gitignore_not_the_pull_requests(repo, tmp_path):
    base_branch(repo, {".gitignore": "CLAUDE.md\n"})
    unignore = b"""\
diff --git a/.gitignore b/.gitignore
--- a/.gitignore
+++ b/.gitignore
@@ -1 +1,2 @@
 CLAUDE.md
+!CLAUDE.md
"""
    diff = unignore + added("CLAUDE.md", "sub/.gitignore")
    assert hits(check(diff, rules_file(tmp_path, IGNORED_RULE))) == ['{"path": "CLAUDE.md"']


def test_ignored_skips_tracked_files(repo, tmp_path):
    base_branch(repo, {".gitignore": "vendor/\n", "vendor/kept.js": "x"}, force=["vendor/kept.js"])
    diff = added("vendor/kept.js", "vendor/new.js")
    assert hits(check(diff, rules_file(tmp_path, IGNORED_RULE))) == ['{"path": "vendor/new.js"']


def test_ignored_outside_a_checkout_warns_and_passes(tmp_path):
    rules = rules_file(tmp_path, IGNORED_RULE)
    outside = tmp_path / "outside"
    outside.mkdir()
    command = [sys.executable, "-I", str(ROOT / "pr-hygiene.py"), str(rules)]
    env = {"PATH": os.environ["PATH"], "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    result = subprocess.run(
        command, input=added("CLAUDE.md"), capture_output=True, cwd=outside, env=env, check=False
    )
    assert result.returncode == 0
    assert result.stdout == b""
    assert b"check out the base branch" in result.stderr


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
