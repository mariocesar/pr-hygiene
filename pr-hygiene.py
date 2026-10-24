#!/usr/bin/env python3
"""Check a unified diff against pr-hygiene rules.

Usage: git diff --diff-filter=d main | uv run pr-hygiene.py rules.yml [more.yml ...]
Prints one JSON object per offending file (path, rule, severity, message) and exits 1.
Rules files are read in order: a later one replaces rules of the same name and adds to exclude.
"""

import json
import re
import sys
from pathlib import Path

import pathspec
import unidiff
import yaml

SEVERITIES = ["cleanup", "hold", "block"]


def load_rules(files):
    rules = {}
    exclude = []
    for file in files:
        data = yaml.safe_load(Path(file).read_text(encoding="utf-8")) or {}
        exclude += data.get("exclude", [])
        for rule in data.get("rules", []):
            name = rule.get("name")
            if not name:
                sys.exit(f"{file}: every rule needs a name")
            if rule.get("enabled", True) is False:
                rules.pop(name, None)
                continue
            for key in ("severity", "paths", "message"):
                if key not in rule:
                    sys.exit(f"{file}: rule {name} needs {key}")
            if rule["severity"] not in SEVERITIES:
                sys.exit(f"{file}: rule {name} has unknown severity {rule['severity']}")
            rules[name] = {
                "rule": name,
                "severity": rule["severity"],
                "paths": pathspec.GitIgnoreSpec.from_lines(rule["paths"]),
                "content": re.compile(rule["content"]) if "content" in rule else None,
                "message": rule["message"].strip(),
            }
    return list(rules.values()), pathspec.GitIgnoreSpec.from_lines(exclude)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip())
    rules, exclude = load_rules(sys.argv[1:])
    diff = sys.stdin.buffer.read().decode("utf-8", "replace")
    found = False
    for file in unidiff.PatchSet(diff):
        if file.is_removed_file or exclude.match_file(file.path):
            continue
        added = [line.value.rstrip("\n") for hunk in file for line in hunk if line.is_added]
        hits = [
            rule
            for rule in rules
            if rule["paths"].match_file(file.path)
            and (rule["content"] is None or any(rule["content"].search(line) for line in added))
        ]
        if hits:
            worst = max(hits, key=lambda rule: SEVERITIES.index(rule["severity"]))
            hit = {key: worst[key] for key in ("rule", "severity", "message")}
            print(json.dumps({"path": file.path, **hit}))
            found = True
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
