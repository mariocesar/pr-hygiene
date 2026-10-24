# PR Hygiene

[![CI](https://github.com/mariocesar/pr-hygiene/actions/workflows/ci.yml/badge.svg)](https://github.com/mariocesar/pr-hygiene/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mariocesar/pr-hygiene?sort=semver)](https://github.com/mariocesar/pr-hygiene/releases)
[![License](https://img.shields.io/github/license/mariocesar/pr-hygiene)](LICENSE)

A GitHub Action for the files that shouldn't be in a pull request: editor folders, fonts nobody
asked for, `.env` files, and the nastier kind that runs code on a maintainer's machine the moment
the branch is checked out. It reads the changed files through the GitHub API, matches them against
a rules file and, depending on what it finds, labels the pull request, turns it into a draft, or
closes it. The code in the pull request is never checked out.

## Quick start

```yaml
# .github/workflows/pr-hygiene.yml
name: PR hygiene

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:
    inputs:
      pr:
        description: Pull request number to check
        type: string
        required: true
      dry_run:
        description: Only report, do not label, draft, close or comment
        type: boolean
        default: true

permissions:
  pull-requests: write
  issues: write

concurrency:
  group: pr-hygiene-${{ github.event.pull_request.number || inputs.pr }}
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      # No checkout. The action reads the pull request through the API.
      - uses: mariocesar/pr-hygiene@v1
        with:
          pr-number: ${{ inputs.pr }}
          dry-run: ${{ inputs.dry_run }}
          draft-token: ${{ secrets.PR_DRAFT_TOKEN }}
```

Pin to a commit SHA with the version in a comment (`uses: mariocesar/pr-hygiene@<sha> # v1.0.0`)
and Dependabot will keep both current. `PR_DRAFT_TOKEN` is optional, see
[Converting to draft](#converting-to-draft).

If you'd rather see what it does before it does anything, run the workflow from the Actions tab
with a pull request number and `dry_run` ticked. The findings show up in the job log and as a
failed check, and the pull request itself isn't touched.

## What happens

Each file the pull request adds or changes is matched against every rule. Rules carry a severity,
and the worst match sets the outcome:

| Worst match | Check | Labels | Pull request | Comment |
|---|---|---|---|---|
| none | passes | `needs-cleanup` removed if the action had added it | unchanged | the earlier comment, if any, is edited to say the files are gone |
| cleanup | fails | `needs-cleanup` | converted to draft | thanks, the files grouped by reason, how to remove them, and a note that the check runs again on every push |
| hold | fails | `do-not-check-out`, plus `needs-cleanup` when there are cleanup files too | converted to draft | same list, ending with "A maintainer will look at this before anything else happens here." |
| block | fails | `do-not-check-out` | closed | "Closing this pull request. The branch contains: ...", plus an issue titled "Block @author" for the repository owner with the `gh api` command to block the account and the report-abuse link |

A few details worth knowing:

- `do-not-check-out` stays until a maintainer removes it by hand. The action adds it but never
  takes it off, so the label always means nobody has looked yet.
- There is one comment per pull request. On later pushes the action finds it by a hidden marker
  and edits it rather than posting a new one.
- Owners, members and collaborators get the failed check and the annotations, nothing more. No
  label, no comment, no draft. The `trusted-associations` input controls who counts.
- Pull requests opened by bots are skipped entirely.
- `dry-run` keeps the failed check and the annotations and skips everything else.
- Missing labels are created on the fly, `needs-cleanup` in amber and `do-not-check-out` in red.

## Inputs

| Input | Default | Description |
|---|---|---|
| `rules` | | Path to your rules file, relative to the workspace, which means the base branch has to be checked out. Empty uses the bundled [`rules.yml`](rules.yml). |
| `extend` | `true` | Layer your rules file on the bundled rules. A rule with the same name replaces the bundled one, `enabled: false` drops it. Set to `false` to use your file alone. |
| `pr-number` | | Pull request number. Empty takes it from the event; set it for `workflow_dispatch`. |
| `dry-run` | `false` | Report only. No label, comment, draft, close or issue. |
| `draft-token` | | Personal access token for converting the pull request to a draft. See [Converting to draft](#converting-to-draft). |
| `cleanup-label` | `needs-cleanup` | Label for pull requests with files to remove. |
| `hold-label` | `do-not-check-out` | Label for pull requests a maintainer should look at before anyone checks them out. |
| `trusted-associations` | `OWNER,MEMBER,COLLABORATOR` | Author associations that only get a failed check. |
| `block-issue` | `true` | On a block, open an issue asking the repository owner to block the author. |
| `github-token` | `${{ github.token }}` | Token for the GitHub API. Needs `pull-requests: write`, and `issues: write` for blocks. |

## Outputs

| Output | Description |
|---|---|
| `worst` | Worst severity found: `none`, `cleanup`, `hold` or `block`. |
| `count` | Number of files that matched a rule. |
| `hits` | JSON array of `{path, rule, severity, message}`, one per matched file. |

## Rules

The bundled [`rules.yml`](rules.yml) covers what doesn't belong in any repository:

| Severity | Rule | Fires on |
|---|---|---|
| block | `editor-autorun-task` | `.vscode/tasks.json` with a task that runs when the folder opens |
| block | `editor-automatic-tasks` | `.vscode/settings.json` turning automatic tasks on |
| block | `script-in-binary-name` | text inside a file named like a font, image or archive |
| block | `python-startup-hook` | `.pth`, `sitecustomize.py`, `usercustomize.py` |
| hold | `whitespace-padding` | a line pushed off the screen by a hundred spaces or more |
| hold | `escaped-identifiers` | names written as runs of `\u00XX` escapes |
| hold | `invisible-characters` | zero-width, bidi and other invisible unicode |
| hold | `download-piped-to-shell` | `curl ... \| sh` in code and config files |
| hold | `encoded-execution` | `eval`/`exec` of base64, hex or compiled strings |
| cleanup | `editor-settings`, `os-files`, `ai-assistant-config`, `node-modules`, `build-leftovers`, `local-environment`, `scratch-files`, `archives` | the usual files that have no business in a change |

### Your own rules

Most projects have a few more: fonts in a library that ships none, `dist/` where builds aren't
committed, `package.json` where there is no JavaScript. Put those in a file in your repository,
check out the base branch so the action can read it, and point `rules` at it:

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: write

steps:
  # The base branch, for the rules file. Never the pull request.
  - uses: actions/checkout@<sha> # v7
    with:
      persist-credentials: false
  - uses: mariocesar/pr-hygiene@<sha> # v1
    with:
      rules: .github/pr-hygiene.yml
```

A rules file is YAML with an optional `exclude` list and a `rules` list:

```yaml
# Files that are never checked, as .gitignore patterns.
exclude: ["tests/fixtures/**"]

rules:
  - name: fonts                 # short id, shown in the check output
    severity: cleanup           # cleanup, hold or block
    paths: ["*.ttf", "*.woff2"] # .gitignore patterns, "!" negates
    message: Font files. Remove them, this project ships no fonts.

  - name: migrations-by-hand
    severity: hold
    paths: ["**/migrations/*.py"]
    content: 'RunSQL'           # Python regex; fires only if an added line matches
    message: Raw SQL in a migration. A maintainer will check it.

  - name: ai-assistant-config   # drop a bundled rule
    enabled: false
```

Patterns work like `.gitignore`: without a `/` they match a file name at any depth, with one they
are anchored at the root, and `**` spans directories.

By default your file is layered on top of the bundled rules, so you only write what's specific to
your project. Reuse a bundled rule's name to replace it, or give it `enabled: false` to drop it.
With `extend: false` the bundled rules are ignored and only your file counts.

When several rules match one file, the most severe wins. Among equals, the one listed first wins,
and bundled rules come before yours.

Content rules only see the lines the pull request adds. The API doesn't return a patch for binary
files or for very large ones, so on those only path rules can fire.

To try a rules file against a local branch:

```sh
git diff --diff-filter=d main | uv run pr-hygiene.py rules.yml .github/pr-hygiene.yml
```

## Security

- The pull request's code is never checked out or executed. [`action.js`](action.js) rebuilds
  the diff from what `pulls.listFiles` returns and [`pr-hygiene.py`](pr-hygiene.py) parses it on
  the runner. The parser has three dependencies, pinned in `uv.lock`.
- The workflow runs on `pull_request_target`, which is what gives it a token that can label,
  comment on and close pull requests from forks. That event has a bad reputation, deservedly:
  a workflow that checks out and runs the pull request's code under it hands the fork a write
  token. This action does neither, and the quick start has no checkout step at all. If you check
  out the base branch for your rules file, that is your own code.
- Only `pull-requests: write` and `issues: write` are needed. Declare exactly that in the
  workflow's `permissions` block.
- The actions this one uses are pinned by commit SHA and the Python side by lockfile. Dependabot
  keeps both current.

### Converting to draft

`GITHUB_TOKEN` can't convert pull requests from forks to draft; the API answers "Resource not
accessible by integration". A personal access token passed as `draft-token` gets around that. A
fine-grained token with "Pull requests: read and write" on the repository is enough. Without one,
the action logs a warning, applies the label anyway, and the comment says "put this on hold"
rather than "turned this into a draft".

## FAQ

**A rule fires on a file that's fine.** Redefine the rule in your own file with narrower `paths`
(negations work, `"!docs/**"`), or drop it with `enabled: false`. For a directory the action should
never look at, such as test fixtures, use `exclude`.

**How do I clear `do-not-check-out`?** Look at the branch, then remove the label. The action won't
do it for you; that's the point of the label.

**A maintainer's pull request failed the check.** Trusted authors still get the failed check and
the annotations, they just don't get labelled, drafted or closed. Change who's trusted with
`trusted-associations`.

**The pull request wasn't converted to draft.** See [Converting to draft](#converting-to-draft).

**Can I run it without it acting?** Set `dry-run: true`, or run the workflow by hand with the
`dry_run` input from the quick start.

**Does it look at the whole repository?** No, only at what the pull request adds or changes.

## Why this exists

In October 2026 [sorl-thumbnail](https://github.com/jazzband/sorl-thumbnail) received a pull
request that touched 27 files and looked like someone had committed their whole working directory:
a `.vscode` folder, a `public/fonts` directory full of icon fonts, an edited `.gitignore`. Looking
closer, `tasks.json` had a task set to run as soon as the folder opened in the editor,
`settings.json` turned automatic tasks on, one of the `.ttf` files was a script, and a font metrics
file hid a line behind a hundred spaces. Checking out the branch to review it would have been the
attack.

The check that caught it started as a workflow inside that repository. This action is the same
check made reusable, with the rules that were specific to sorl-thumbnail moved out into a file
the consumer owns.

## Alternatives

What I looked at before writing this:

- [xalvarez/prevent-file-change-action](https://github.com/xalvarez/prevent-file-change-action)
  matches paths with a regex and fails or closes. No severities, no content rules, no comments.
- [actions/labeler](https://github.com/actions/labeler) labels by path and stops there.
- [Danger](https://danger.systems/) is a DSL for pull request rules. It needs the code checked out
  and has a hard time with tokens on pull requests from forks.
- [Apiiro PRevent](https://github.com/apiiro/PRevent) is a self-hosted GitHub App with Semgrep
  rules for obfuscated code. Capable, but a service of its own to run.
- [chainguard-dev/malcontent-action](https://github.com/chainguard-dev/malcontent-action) runs
  malware heuristics over a checked-out pull request under `pull_request`, so for first-time
  contributors it waits for workflow approval.
- [heckler](https://github.com/intel/heckler) and
  [anti-trojan-source](https://github.com/lirantal/anti-trojan-source) cover invisible unicode and
  nothing else.
- GitHub push rulesets can block paths before they land, but only on private and internal
  repositories on paid plans.

None of them combine reading the diff through the API only, a rules file with severities, and the
label, draft and close outcomes.

## License

[MIT](LICENSE).
