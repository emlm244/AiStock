# Parallel AI Development with Git Worktrees

**Simple workflow for running multiple AI agents in parallel**

---

## The Pattern

**One worktree = One AI = One branch = One PR**

Git worktrees let you check out multiple branches in separate folders. Each AI works in its own folder with its own branch - **physically impossible to conflict**.

---

## Quick Start

### 1. Create worktrees (as many as you want)

```bash
# From your main AiStock directory
cd C:\Users\bc200\AiStock

# Create worktrees for parallel work
git fetch origin
git switch -C main --track origin/main

# Worktree 1: Cursor AI
git worktree add ../AiStock--cursor -b ai/cursor/feature-name origin/main

# Worktree 2: Claude Code CLI
git worktree add ../AiStock--claude -b ai/claude/feature-name origin/main

# Worktree 3: Another AI (Codex, Windsurf, etc.)
git worktree add ../AiStock--codex -b ai/codex/feature-name origin/main

# Add more as needed...
```

**Branch naming**: `ai/<agent-name>/<task-name>`

### 2. Open each AI in its worktree

```bash
# Terminal 1: Cursor
cursor C:\Users\bc200\AiStock--cursor

# Terminal 2: Claude
cd C:\Users\bc200\AiStock--claude
claude

# Terminal 3: Codex or another AI
cd C:\Users\bc200\AiStock--codex
codex
# or just: claude
```

### 3. Each AI works independently

**In each worktree**, the AI:
- Makes changes to the codebase
- Runs tests locally
- Commits when ready

```bash
# In worktree folder (e.g., AiStock--cursor)
git add .
git commit -m "feat: implement feature X"
git push -u origin HEAD
```

### 4. Create PR

```bash
# From the worktree folder
gh pr create --base main --title "feat: your feature" --body "Description of changes"
```

### 5. Bugbot reviews automatically

**Cursor Bugbot** (already active on your repo):
- Automatically summarizes PRs
- Reviews code changes
- Flags issues

**Manual trigger**: Comment `cursor review` on any PR to force a review.

### 6. Merge when ready

Once Bugbot approves and CI passes, merge the PR (manually or with auto-merge enabled).

---

## Example: 3 AIs in Parallel

**Goal**: Add analytics features to AiStock

```bash
# Create 3 worktrees
cd C:\Users\bc200\AiStock
git worktree add ../AiStock--cursor  -b ai/cursor/sharpe-ratio  origin/main
git worktree add ../AiStock--claude1 -b ai/claude1/drawdown     origin/main
git worktree add ../AiStock--claude2 -b ai/claude2/performance  origin/main

# Terminal 1: Cursor
cursor C:\Users\bc200\AiStock--cursor
# Task: "Add Sharpe ratio calculation to AnalyticsReporter"

# Terminal 2: Claude #1
cd C:\Users\bc200\AiStock--claude1
claude
# Task: "Add drawdown tracking to Portfolio"

# Terminal 3: Claude #2
cd C:\Users\bc200\AiStock--claude2
claude
# Task: "Add performance chart generation"

# Each AI works for 10-20 minutes...

# Each pushes when done
cd C:\Users\bc200\AiStock--cursor  && git push -u origin HEAD && gh pr create --base main
cd C:\Users\bc200\AiStock--claude1 && git push -u origin HEAD && gh pr create --base main
cd C:\Users\bc200\AiStock--claude2 && git push -u origin HEAD && gh pr create --base main

# Bugbot reviews all 3 PRs
# CI runs on all 3 PRs
# Merge when green ✅

# Result: 3 features in parallel instead of 30-60 minutes serial
```

---

## How Conflicts Are Avoided

### 1. Physical Isolation
Each AI has its own folder:
```
C:\Users\bc200\AiStock           ← Main repo
C:\Users\bc200\AiStock--cursor   ← Cursor AI workspace
C:\Users\bc200\AiStock--claude1  ← Claude AI workspace
C:\Users\bc200\AiStock--claude2  ← Another Claude workspace
```

They **cannot** overwrite each other's files because they're in different directories.

### 2. Separate Branches
Each worktree has its own branch:
```
ai/cursor/sharpe-ratio   ← Cursor's changes
ai/claude1/drawdown      ← Claude #1's changes
ai/claude2/performance   ← Claude #2's changes
```

### 3. Merge Discipline
- First PR merges cleanly ✅
- Second PR: If it touches same lines, GitHub will show conflict
  - Rebase manually: `git fetch origin main && git rebase origin/main`
  - Or let GitHub's merge queue handle it automatically

### 4. Optional: Path Isolation
Assign each AI to specific directories:

```bash
# Cursor: only brokers
git -C ../AiStock--cursor sparse-checkout init --cone
git -C ../AiStock--cursor sparse-checkout set aistock/brokers/ tests/

# Claude 1: only session layer
git -C ../AiStock--claude1 sparse-checkout init --cone
git -C ../AiStock--claude1 sparse-checkout set aistock/session/ tests/

# Claude 2: only core logic
git -C ../AiStock--claude2 sparse-checkout init --cone
git -C ../AiStock--claude2 sparse-checkout set aistock/fsd.py aistock/portfolio.py tests/
```

Now they **physically cannot** touch the same files.

---

## Cursor Bugbot Configuration

Bugbot is already active on your repo. It uses rules from `.cursor/BUGBOT.md` (if you create one).

**Optional**: Create project-specific review rules:

```markdown
# .cursor/BUGBOT.md
## Critical Rules for AiStock

- ❌ BLOCK: Float for money (require Decimal)
- ❌ BLOCK: Shared state without locks
- ❌ BLOCK: Imports from aistock/_legacy/
- ⚠️ WARN: Missing tests for new features
```

Then Bugbot will check these rules on every PR.

---

## Cleanup After Merging

```bash
# List all worktrees
git worktree list

# Remove worktrees after PRs are merged
git worktree remove ../AiStock--cursor
git worktree remove ../AiStock--claude1
git worktree remove ../AiStock--claude2

# Delete remote branches (if not auto-deleted)
git push origin --delete ai/cursor/sharpe-ratio
git push origin --delete ai/claude1/drawdown
git push origin --delete ai/claude2/performance
```

---

## Scaling

**Works with 1, 2, 3, 4+ AIs:**
```bash
# Just create more worktrees
git worktree add ../AiStock--ai4 -b ai/ai4/task origin/main
git worktree add ../AiStock--ai5 -b ai/ai5/task origin/main
# etc.
```

**Cursor 2.0** supports up to **8 parallel agents** using this exact pattern.

---

## Optional: GitHub Auto-Merge

Enable in repo settings for hands-free merging:

1. Go to: https://github.com/emlm244/AiStock/settings/branches
2. Add rule for `main`:
   - ✅ Require pull request reviews
   - ✅ Require status checks to pass (CI: lint, test, typecheck)
   - ✅ **Allow auto-merge**

Then after creating a PR:
```bash
gh pr merge --auto --squash
```

PR will auto-merge when Bugbot approves + CI passes.

---

## Tips

### Reuse Worktrees
Don't delete worktrees after every task - reuse them:
```bash
cd ../AiStock--cursor
git fetch origin main
git checkout -b ai/cursor/new-task origin/main
# Work on new task...
```

### Check Current Worktrees
```bash
git worktree list
```

### Quick PR Creation
```bash
# From worktree
git push -u origin HEAD && gh pr create --base main --fill
```

### Force Bugbot Review
Comment on any PR:
```
cursor review
```

---

## Real Productivity Gains

From research on parallel AI development:
- **Serial**: 1 feature at a time, 30-60 min each = 3 hours for 3 features
- **Parallel**: 3 features simultaneously = ~30-45 minutes total

**Key**: Git worktrees eliminate the bottleneck of context switching between branches.

---

## Summary

**Vibe coding workflow**:
1. Create worktrees: `git worktree add ../AiStock--<name> -b ai/<name>/<task> origin/main`
2. Open each in its own terminal/editor
3. Let AIs work independently (no conflicts)
4. Push + create PRs
5. Bugbot reviews automatically
6. Merge when green
7. Remove worktrees when done

**No complex scripts. No API keys. Just git worktrees + Cursor Bugbot.**

---

**Ready to try?**

```bash
# Create your first parallel worktree
git worktree add ../AiStock--cursor -b ai/cursor/my-feature origin/main
cursor ../AiStock--cursor
# Tell Cursor AI what to build
```
