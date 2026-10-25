// The GitHub side of the action, called from action.yml. Rebuilds the diff from the API, runs
// pr-hygiene.py through uv, then labels, drafts, comments or closes by the worst severity.
const fs = require('fs');
const path = require('path');

const SEVERITIES = ['cleanup', 'hold', 'block'];
const MARKER = '<!-- pr-hygiene -->';

module.exports = async ({ github, context, core, exec }) => {
  const { owner, repo } = context.repo;
  const env = process.env;
  const dryRun = env.DRY_RUN === 'true';
  const labels = { cleanup: env.CLEANUP_LABEL, hold: env.HOLD_LABEL };
  const colors = { [labels.cleanup]: 'e4a11b', [labels.hold]: 'b60205' };

  // Fetch the pull request rather than trusting the event payload: labels and draft state
  // may have changed since.
  const number = Number(env.PR_NUMBER) || (context.payload.pull_request || {}).number;
  if (!number) {
    return core.setFailed('No pull request number. Set the pr-number input.');
  }
  const pr = (await github.rest.pulls.get({ owner, repo, pull_number: number })).data;
  const login = pr.user.login;
  if (pr.user.type === 'Bot') {
    return core.info(`${login} is a bot account, skipping`);
  }
  const trustedAssociations = env.TRUSTED.split(',').map((s) => s.trim());
  const trusted = trustedAssociations.includes(pr.author_association);

  // Rebuild the diff from the API so the pull request's code never reaches the runner.
  const files = await github.paginate(github.rest.pulls.listFiles, {
    owner,
    repo,
    pull_number: pr.number,
    per_page: 100,
  });
  const diff = files
    .filter((file) => file.status !== 'removed')
    .map((file) => {
      const name = file.filename;
      const header = `diff --git a/${name} b/${name}\n`;
      if (!file.patch) {
        return `${header}Binary files a/${name} and b/${name} differ\n`;
      }
      return `${header}--- a/${name}\n+++ b/${name}\n${file.patch}\n`;
    })
    .join('');

  // The rules: the bundled file, the consumer's file, or both.
  const rules = [];
  if (env.EXTEND === 'true' || !env.RULES) {
    rules.push(path.join(env.ACTION_PATH, 'rules.yml'));
  }
  if (env.RULES) {
    const file = path.resolve(env.GITHUB_WORKSPACE, env.RULES);
    if (!fs.existsSync(file)) {
      return core.setFailed(`${env.RULES} not found. Check out the base branch first.`);
    }
    rules.push(file);
  }

  // Run the matcher in the workspace, where "ignored" rules read the base branch's .gitignore.
  // It exits 1 both for hits and for a broken rules file; the output tells them apart.
  const uvArgs = ['run', '--quiet', '--frozen', '--no-dev', '--project', env.ACTION_PATH];
  const script = path.join(env.ACTION_PATH, 'pr-hygiene.py');
  const run = await exec.getExecOutput('uv', [...uvArgs, script, ...rules], {
    cwd: env.GITHUB_WORKSPACE,
    input: Buffer.from(diff),
    ignoreReturnCode: true,
    silent: true,
  });
  const lines = run.exitCode <= 1 ? run.stdout.split('\n').filter(Boolean) : [];
  const hits = lines.map((line) => JSON.parse(line));
  if (run.exitCode > 1 || (run.exitCode === 1 && hits.length === 0)) {
    return core.setFailed(run.stderr.trim() || `pr-hygiene.py exited with ${run.exitCode}`);
  }
  if (run.stderr.trim()) {
    core.warning(run.stderr.trim());
  }

  const severities = SEVERITIES.filter((s) => hits.some((hit) => hit.severity === s));
  const worst = severities[severities.length - 1] || 'none';
  core.setOutput('worst', worst);
  core.setOutput('count', hits.length);
  core.setOutput('hits', JSON.stringify(hits));

  // One comment per pull request, found by the marker and edited in place.
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: pr.number,
    per_page: 100,
  });
  const previous = comments.find((c) => c.body && c.body.includes(MARKER));

  const comment = async (text) => {
    const body = `${MARKER}\n${text}`;
    if (previous) {
      await github.rest.issues.updateComment({ owner, repo, comment_id: previous.id, body });
    } else {
      await github.rest.issues.createComment({ owner, repo, issue_number: pr.number, body });
    }
  };

  // One bullet per message with the files that share it, so the comment groups by reason.
  const listed = (items) => {
    const byMessage = new Map();
    for (const hit of items) {
      const paths = byMessage.get(hit.message) || [];
      byMessage.set(hit.message, [...paths, hit.path]);
    }
    return [...byMessage].map(([message, paths]) => {
      const names = paths.map((p) => `\`${p}\``).join(', ');
      return `- ${names}\n  ${message}`;
    });
  };

  const addLabels = async (names) => {
    for (const name of names) {
      try {
        await github.rest.issues.createLabel({ owner, repo, name, color: colors[name] });
      } catch {
        // Already exists.
      }
    }
    await github.rest.issues.addLabels({ owner, repo, issue_number: pr.number, labels: names });
  };

  if (worst === 'none') {
    core.notice(`#${pr.number} passes`);
    if (dryRun || trusted) {
      return;
    }
    if (pr.labels.some((label) => label.name === labels.cleanup)) {
      await github.rest.issues.removeLabel({
        owner,
        repo,
        issue_number: pr.number,
        name: labels.cleanup,
      });
    }
    if (previous) {
      await comment(`Thanks @${login}, the files that didn't belong are gone now.`);
    }
    return;
  }

  for (const hit of hits) {
    core.error(`${hit.severity}: ${hit.path}: ${hit.message} [${hit.rule}]`);
  }
  core.setFailed(
    `#${pr.number}: ${hits.length} file(s) break the hygiene rules, worst is ${worst}`,
  );
  if (dryRun) {
    return core.info('Dry run, the pull request was left as it is.');
  }
  if (trusted) {
    return core.info(`${pr.author_association} author, only the check fails.`);
  }

  if (worst === 'block') {
    const flagged = hits.filter((hit) => hit.severity === 'block');
    await addLabels([labels.hold]);
    const intro = 'Closing this pull request. The branch contains:';
    await comment([intro, '', ...listed(flagged)].join('\n'));
    await github.rest.pulls.update({ owner, repo, pull_number: pr.number, state: 'closed' });
    if (env.BLOCK_ISSUE !== 'true') {
      return;
    }

    // One open issue per author asks the maintainer to block them.
    const title = `Block @${login}`;
    const body = [
      MARKER,
      `@${owner}: #${pr.number} was closed by the PR hygiene check because of:`,
      '',
      ...listed(flagged),
      '',
      'To block the account and report it:',
      '',
      '```',
      `gh api -X PUT /user/blocks/${login}`,
      '```',
      'https://github.com/contact/report-abuse',
    ].join('\n');
    const issues = await github.paginate(github.rest.issues.listForRepo, {
      owner,
      repo,
      state: 'open',
      per_page: 100,
    });
    const existing = issues.find(
      (issue) =>
        !issue.pull_request && issue.title === title && (issue.body || '').includes(MARKER),
    );
    if (existing) {
      await github.rest.issues.createComment({ owner, repo, issue_number: existing.number, body });
    } else {
      await github.rest.issues.create({ owner, repo, title, body });
    }
    return;
  }

  // cleanup or hold: label it, draft it, explain.
  await addLabels(severities.map((s) => labels[s]));

  let drafted = pr.draft;
  if (!drafted) {
    // GITHUB_TOKEN cannot draft pull requests from forks; a personal token can.
    const token = env.DRAFT_TOKEN;
    const auth = token ? { headers: { authorization: `token ${token}` } } : {};
    const mutation = `mutation($id: ID!) {
      convertPullRequestToDraft(input: {pullRequestId: $id}) { clientMutationId }
    }`;
    try {
      await github.graphql(mutation, { id: pr.node_id, ...auth });
      drafted = true;
    } catch (error) {
      core.warning(`Could not convert #${pr.number} to draft: ${error.message}`);
    }
  }

  const hints = [
    'To drop a file from the branch without deleting your copy: `git rm -r --cached <path>`.',
    `To undo a change to a file: \`git checkout ${pr.base.ref} -- <path>\`.`,
    'Then commit and push.',
  ].join(' ');
  const onPass = drafted ? 'mark the pull request ready for review.' : 'the label comes off.';
  const footer =
    worst === 'hold'
      ? 'A maintainer will look at this before anything else happens here.'
      : `${hints}\n\nThis check runs again on every push. Once it passes, ${onPass}`;
  const action = drafted ? 'turned this into a draft' : 'put this on hold';
  await comment(
    [
      `Hi @${login}, thanks for the patch.`,
      '',
      `I ${action} because of these files:`,
      '',
      ...listed(hits),
      '',
      footer,
    ].join('\n'),
  );
};
