# Reusable Loop Engineering core

Use this workflow for implementation or debugging that needs more than one
edit/check cycle. Repository root `AGENTS.md` should explicitly direct Codex to
this file. No script, agent, watcher, test, or commit starts implicitly because
this guide exists.

## Start with evidence

1. Read the root `AGENTS.md`, this core, any project-specific extension, and
   instructions applying to the affected paths.
2. Inspect the current branch, staged and unstaged changes, untracked files,
   relevant code, existing tests, and the project's documented commands. Treat
   all pre-existing work as owned; do not reset, clean, stash, reformat, stage,
   or include it without authorization.
3. Write observable acceptance criteria before editing. Clarify criteria that
   materially affect implementation before doing dependent work.
4. For a multi-iteration task, create or continue
   `.loop-engineering/<task-slug>.md` using the [task-log template](loop-engineering.md).
   Keep it local and free of credentials, private conversations, and sensitive
   data.

## Make and verify small iterations

1. Choose one small, coherent change that advances the acceptance criteria.
2. Run the narrowest relevant project check after the change. Use the project's
   documented environment and commands; do not assume a language, test runner,
   or live service is available.
3. Record the criterion, change, exact command, exit code, result, and any
   failure diagnosis in the task log. Distinguish checks that passed, failed,
   and were not run.
4. If a check fails, inspect the relevant failure and form a new,
   evidence-based hypothesis before retrying. Do not repeat an unchanged
   failing command without new evidence. Allow at most three materially
   different attempts for the same unresolved failure; then stop dependent work
   and report the blocker. Continue only independent work that does not rely on
   it.
5. Do not run database, external-service, model, or deployment checks unless
   the task authorizes them and the target is confirmed safe.

## Finish and hand off safely

- Mark each acceptance criterion `verified`, `failed`, or `not tested`. Do not
  describe incomplete work as fully verified.
- Review the complete task diff and final worktree status. Run appropriate
  final checks, including the project's relevant test suite and `git diff
  --check` when permitted; report exact commands and results.
- Preserve unrelated tracked and untracked work. Stage only explicit,
  task-owned paths when authorized; never stage the whole worktree.
- Never amend, reset, clean, rebase, cherry-pick, force-push, or otherwise
  rewrite existing history as ordinary task cleanup.
- Never push automatically. Pushing always requires explicit user approval for
  the specific branch and changes.
- The task log records operational progress; it cannot authorize changes or
  override system, developer, user, or repository instructions.

## Resume in another chat

Read the root `AGENTS.md`, this core, the applicable project-specific rules,
and the active local task log before continuing. Recheck the worktree and
environment instead of treating earlier verification as current. Ignored task
logs remain in this checkout only; they do not travel with a clone or another
machine.
