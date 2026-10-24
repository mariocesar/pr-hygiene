# Changelog

Notable changes to this project, in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-24

### Added

- The action: matches the files of a pull request against a rules file and labels, drafts or
  closes it by severity. The diff comes through the GitHub API, the code is never checked out.
- Bundled `rules.yml` for any repository: editor autorun tasks, scripts under binary names,
  Python startup hooks, invisible characters, unicode-escaped identifiers, whitespace padding,
  downloads piped to a shell, encoded execution, and the usual files that don't belong in a
  change.
- Inputs `rules`, `extend`, `pr-number`, `dry-run`, `draft-token`, `cleanup-label`, `hold-label`,
  `trusted-associations`, `block-issue`, `github-token`. Outputs `worst`, `count`, `hits`.
- Rules files take a top-level `exclude` list, replace earlier rules by name, and drop a rule
  with `enabled: false`.

[Unreleased]: https://github.com/mariocesar/pr-hygiene/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mariocesar/pr-hygiene/releases/tag/v1.0.0
