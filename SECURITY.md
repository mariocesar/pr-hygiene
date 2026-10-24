# Security

This action is itself a security control, so a bug in it is worse than usual.

## Reporting

Use [private vulnerability reporting](https://github.com/mariocesar/pr-hygiene/security/advisories/new)
on this repository rather than a public issue. You will hear back within a week.

Rules that can be bypassed count too. If you have a diff that slips through, include it.

## Supported versions

The latest release of the current major version. Pin by commit SHA and let Dependabot move the
pin.

## What the action does and doesn't do

- It never checks out or runs code from the pull request. The diff comes through the GitHub API
  and is parsed by the Python matcher on the runner.
- It acts with whatever token the workflow gives it. With the default `GITHUB_TOKEN` under
  `pull_request_target`, that is the permissions declared in the workflow and nothing from the
  fork.
- The optional `draft-token` is a personal access token used for a single GraphQL call, the one
  that converts the pull request to a draft. Give it the smallest scope that works.
- The rules are pattern matching, not analysis. They catch known shapes of files that don't
  belong. This is not a malware scanner.
