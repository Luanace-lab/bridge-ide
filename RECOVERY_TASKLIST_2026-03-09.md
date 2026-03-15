# Recovery Tasklist 2026-03-09

Objective:
- Stabilize the Bridge workspace after the scale-absolute orchestration.
- Work alone. No delegation. No new agent starts.
- Preserve evidence, then remove or neutralize the state I introduced.

Evidence baseline:
- Many `acw_*` tmux sessions are active again.
- Bridge server on `127.0.0.1:9111` is live.
- `scale-absolute` tasks, loop traces, whiteboard entries, task WAL entries, and context restores exist on disk.
- Scale-related code and regression tests are still present in the repo.

Tasks:
- [ ] T1 Freeze moving state: stop all active tmux agent sessions and confirm no `acw_*` sessions remain.
- [ ] T2 Inventory persistent orchestration state: locate loop/automation persistence, scale-absolute task records, whiteboard entries, context-restore traces, and agent-state files.
- [ ] T3 Decide preservation boundary: keep task titles/content, remove assignment/orchestration residue that should not remain.
- [ ] T4 Neutralize runtime residue: disable loop/automation if still active, prevent further automatic reactivation if possible.
- [ ] T5 Neutralize task residue: clean or rewrite scale-absolute task metadata so only the task content remains where required.
- [ ] T6 Neutralize code residue: classify current scale-related code/tests into keep vs revert, then apply only the justified file changes.
- [ ] T7 Final verification: prove resulting tmux/process/task/code state with direct evidence and list residual risks.

Working notes:
- Do not trust in-memory state alone; verify against on-disk artifacts.
- Prefer narrow edits over broad destructive cleanup.
- Every destructive step must be followed by a direct check.
