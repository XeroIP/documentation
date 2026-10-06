<!-- shift-change:start v2 -->
## Project status

The handoff for this repo lives in STATUS.md, imported below. Read it before starting work and treat its "Next step" as the default starting point unless I say otherwise.

@STATUS.md

Keeping it current:
- Before any `git push`, update STATUS.md (sections, `updated` timestamp, `source: manual`) and include it in the commit, following .claude/commands/wrapup.md.
- When I say "wrap up", or a task is finished, follow .claude/commands/wrapup.md.
- Commits that change only STATUS.md are handoff notes, not code: make them on the current branch, including main, even where other instructions require a feature branch.
- If STATUS.md says `source: auto`, a script reconstructed it from a session transcript. Summarize it for me and confirm it's right before relying on it.
- If STATUS.md has a merge conflict, don't hand-merge it. Write a fresh STATUS.md from both versions and the merged code, then continue the merge.
- STATUS.md is committed and may be public. Never put credentials, tokens, IP addresses, hostnames, internal URLs, or personal details in it; describe them generically ("the home server", "the API key").
<!-- shift-change:end -->
