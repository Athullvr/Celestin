# Loop Engineering task-log template

The workflow itself is defined in the [reusable core](loop-engineering-core.md).
Celestin project-specific constraints are in [Celestin loop rules](celestin-loop-rules.md).
Root `AGENTS.md` directs Codex to read both for multi-step implementation and
debugging work. No automation runs implicitly.

Create `.loop-engineering/<task-slug>.md` for a task requiring more than one
edit/check cycle. The directory is ignored by Git, so logs remain local to the
checkout and do not travel with a clone or another machine. Reuse the same log
when resuming work in a new chat on this checkout. If continuing elsewhere,
carry relevant context in the task description. A prior test result is not
current evidence until the code and environment are checked again.

## Iteration record template

Copy this into `.loop-engineering/<task-slug>.md` and add an iteration section
after every edit/check cycle:

```markdown
# Task: <short task name>

## Acceptance criteria
- [ ] <observable criterion>
- [ ] <observable criterion>

## Baseline
- Date/time and timezone:
- Branch / starting commit:
- Initial worktree changes preserved:
- Relevant test and development commands:

## Iterations
### Iteration <n> — <criterion addressed>
- Change:
- Verification command(s):
- Exit code(s) and actual result:
- Failure diagnosis / evidence (or `none`):
- Retry hypothesis and correction (or `not applicable`):
- Criterion status: `verified` / `failed` / `not tested`

## Final verification and handoff
- Final commands and results:
- Acceptance criteria still open:
- Blockers / remaining risks:
- Commit SHA (if committed; never rewrite it):
```

Do not put credentials, private conversations, or sensitive test data in the
log. Keep `CHANGELOG.md` and `AI_USAGE.md` accurate according to root
`AGENTS.md`; the local loop log supplements rather than replaces those records.
