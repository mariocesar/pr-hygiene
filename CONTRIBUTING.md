# Contributing

## Setup

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run yamllint --strict .
```

`uv.lock` pins everything. To change a version, edit `pyproject.toml` and run `uv lock`.

The action is three files. `action.yml` declares the inputs, outputs and steps; `action.js` does
the GitHub side, from fetching the diff to labels, comments, drafting and closing; `pr-hygiene.py`
is the matcher. CI runs `node --check action.js`, and that is the whole JavaScript toolchain.

## Tests

Each `tests/fixtures/<name>.diff` goes through the matcher with the bundled rules and the output
is compared byte for byte with `<name>.expected.jsonl`. To add a case, add a diff and its expected
output. Keep fixtures synthetic, don't paste content from a real pull request. Some fixtures exist
in both the `a/ b/` prefixed form and the `diff.noprefix` form because the two parse differently.

Since the fixtures are full of exactly what the rules look for, this repository's own rules file,
`.github/pr-hygiene.yml`, excludes them.

## Rules

A rule goes in the bundled `rules.yml` only if it makes sense for any repository. Rules for one
kind of project (fonts in a Python library, `dist/` where builds aren't committed) belong in that
project's own file; `tests/fixtures/sorl-thumbnail.yml` shows what one looks like.

Regexes for invisible characters use `\N{NAME}` escapes, never the characters themselves. A test
fails if any tracked file outside the fixtures contains one.

## Releasing

1. In `CHANGELOG.md`, move the `Unreleased` entries under a `## [x.y.z] - date` heading.
2. `git tag vx.y.z && git push origin main vx.y.z`
3. The release workflow runs the tests, creates the GitHub release from that changelog section
   and moves the `v1` tag to the new commit. It fails if the changelog has no section for the
   version.
4. To list the release on the Marketplace, edit it on GitHub and tick "Publish this Action to the
   GitHub Marketplace".

Breaking changes to inputs, outputs or the rules schema mean a new major version.
