@AGENTS.md

## Claude Code notes

- Commit or push only when asked. Never stage `journal/` edits you didn't make;
  the user often has uncommitted journal work in progress.
- `git add` specific paths and check `git status` before committing; a failed
  pathspec silently leaves files out of the commit.
- When orchestrating subagents, give each one a disjoint set of files and the
  exact module paths and public names it may rely on from the others.
