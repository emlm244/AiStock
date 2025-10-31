# 🧹 Codebase Cleanup Guide - AIStock

**Date**: 2025-10-31
**Purpose**: Explain what files/directories do and which should be deleted

---

## 📁 File/Directory Explanation

### ❌ Files That SHOULD NOT Be in Git (But Are)

#### 1. **state/** (12 MB) - ❌ DELETE FROM GIT
**What it is**: Runtime trading state and learned FSD (Q-learning) data
**Why it exists**: Persists learned trading patterns between sessions
**Problem**:
- ✗ User-specific learned state (not shareable)
- ✗ Takes up 12 MB in git history
- ✗ Different for each developer
- ✗ Should be generated locally, not shared

**Currently tracked files**:
```
state/fsd_state.json (122 KB)
state/fsd/ai_state.json
state/fsd/experience_buffer.json
state/fsd/performance_history.json
state/fsd/simple_gui_*.json (3 files)
```

**Action**: Remove from git, keep .gitkeep only

---

### ✅ Files Already Ignored (Good!)

#### 2. **.idea/** (34 KB) - ✅ ALREADY IGNORED
**What it is**: PyCharm/IntelliJ IDE configuration
**Why it exists**: IDE stores project settings here
**Status**: ✅ Correctly in .gitignore
**Action**: Delete locally if you don't use PyCharm

---

#### 3. **htmlcov/** (4.3 MB) - ✅ ALREADY IGNORED
**What it is**: HTML coverage reports from pytest-cov
**Why it exists**: Generated when you run `pytest --cov --cov-report=html`
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally (regenerated on next test run)

---

#### 4. **.coverage** (53 KB) - ✅ ALREADY IGNORED
**What it is**: Code coverage data file from pytest-cov
**Why it exists**: Tracks which lines of code were executed during tests
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally (regenerated on next test run)

---

#### 5. **.hypothesis/** (88 KB) - ✅ ALREADY IGNORED
**What it is**: Hypothesis testing framework database
**Why it exists**: Hypothesis is a property-based testing library that generates test cases
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete if you don't use hypothesis tests

---

#### 6. **.pytest_cache/** (24 KB) - ✅ ALREADY IGNORED
**What it is**: pytest cache for faster test runs
**Why it exists**: Caches test results and node IDs
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally (regenerated on next test run)

---

#### 7. **__pycache__/** (12 KB × 6104 instances) - ✅ ALREADY IGNORED
**What it is**: Python bytecode cache
**Why it exists**: Python compiles .py files to .pyc for faster loading
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally (regenerated automatically)

---

#### 8. **.ruff_cache/** (509 KB) - ✅ ALREADY IGNORED
**What it is**: Ruff linter cache
**Why it exists**: Speeds up subsequent linting runs
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally (regenerated on next ruff run)

---

#### 9. **.benchmarks/** (empty) - ✅ ALREADY IGNORED
**What it is**: pytest-benchmark results
**Why it exists**: Stores performance benchmark data
**Status**: ✅ Correctly in .gitignore
**Action**: Safe to delete locally

---

### ✅ Files That SHOULD Be in Git (Keep These)

#### 10. **docs/** - ✅ KEEP IN GIT
**What it is**: Project documentation
**Contents**:
- `FSD_COMPLETE_GUIDE.md` (15 KB) - Comprehensive FSD guide
**Status**: ✅ Properly tracked in git
**Action**: Keep! This is valuable documentation

---

## 🧹 Cleanup Actions

### Priority 1: Remove state/ files from git (CRITICAL)
**Why**: 12 MB of user-specific runtime data doesn't belong in version control

```bash
# 1. Remove from git but keep locally
git rm --cached state/fsd/*.json
git rm --cached state/fsd_state.json

# 2. Update .gitignore to exclude state files
echo "" >> .gitignore
echo "# Trading session state (generated at runtime)" >> .gitignore
echo "state/**/*.json" >> .gitignore
echo "!state/**/.gitkeep" >> .gitignore

# 3. Commit the removal
git add .gitignore
git commit -m "chore: remove runtime state files from git tracking"
```

**Result**:
- ✅ Reduces repo size by 12 MB
- ✅ Each developer generates their own learned state
- ✅ No merge conflicts on state files

---

### Priority 2: Clean up local cache directories (OPTIONAL)
**Why**: Frees up 5+ MB of disk space

```bash
# Delete all cache directories
rm -rf .hypothesis
rm -rf htmlcov
rm -rf .pytest_cache
rm -rf .ruff_cache
rm -rf .benchmarks
rm .coverage

# Delete all __pycache__ directories
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
```

**Result**:
- ✅ Frees ~5-6 MB locally
- ✅ All will be regenerated on next test/lint run
- ✅ No impact on git (already ignored)

---

### Priority 3: Delete IDE files if not needed (OPTIONAL)
**Why**: If you don't use PyCharm, these are unnecessary

```bash
# Only if you DON'T use PyCharm/IntelliJ
rm -rf .idea

# Only if you DON'T use VS Code
rm -rf .vscode

# Only if you DON'T use Cursor
rm -rf .cursor
```

**Result**:
- ✅ Frees ~34 KB per IDE directory
- ✅ No impact on git (already ignored)

---

## 📊 Size Summary

| Directory/File | Size | In Git? | Should Be? | Action |
|----------------|------|---------|------------|--------|
| state/ | 12 MB | ❌ Yes | ❌ No | Remove from git |
| htmlcov/ | 4.3 MB | ✅ No | ✅ No | Delete locally (optional) |
| .ruff_cache/ | 509 KB | ✅ No | ✅ No | Delete locally (optional) |
| .hypothesis/ | 88 KB | ✅ No | ✅ No | Delete locally (optional) |
| .coverage | 53 KB | ✅ No | ✅ No | Delete locally (optional) |
| .idea/ | 34 KB | ✅ No | ✅ No | Delete if not using PyCharm |
| .pytest_cache/ | 24 KB | ✅ No | ✅ No | Delete locally (optional) |
| __pycache__/ | 12 KB | ✅ No | ✅ No | Delete locally (optional) |
| docs/ | 15 KB | ✅ Yes | ✅ Yes | ✅ Keep! |

**Total wasted space in git**: 12 MB (state files)
**Total local cache**: ~5-6 MB (safe to delete)

---

## ✅ Recommended Cleanup Script

```bash
#!/bin/bash
# Complete cleanup script for AIStock

echo "=== AIStock Codebase Cleanup ==="
echo ""

# 1. Remove state files from git
echo "1. Removing state files from git tracking..."
git rm --cached -r state/fsd/*.json 2>/dev/null
git rm --cached state/fsd_state.json 2>/dev/null

# 2. Update .gitignore
echo "2. Updating .gitignore..."
cat >> .gitignore << 'EOF'

# Trading session state (generated at runtime)
state/**/*.json
!state/**/.gitkeep
EOF

# 3. Clean local cache
echo "3. Cleaning local cache directories..."
rm -rf .hypothesis htmlcov .pytest_cache .ruff_cache .benchmarks .coverage
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null

# 4. Commit changes
echo "4. Committing cleanup..."
git add .gitignore
git commit -m "chore: remove runtime state files and update .gitignore

- Remove state/*.json from git tracking (12 MB saved)
- Add state files to .gitignore
- Keep .gitkeep files for directory structure
"

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Summary:"
echo "  - Removed 12 MB of runtime state from git"
echo "  - Cleaned ~5 MB of local cache"
echo "  - Updated .gitignore for future commits"
echo ""
echo "Next: git push origin feature/phase-1-interfaces"
```

---

## 🎯 Why This Matters for Multi-Developer Teams

### Before Cleanup:
- ❌ Developer A commits their learned FSD state
- ❌ Developer B pulls and overwrites their own learned state
- ❌ Merge conflicts on state files every sync
- ❌ 12 MB of unnecessary data in git history

### After Cleanup:
- ✅ Each developer generates their own state locally
- ✅ No state file conflicts
- ✅ Smaller repo size (12 MB saved)
- ✅ Faster clones and pulls

---

## 📝 Files Explanation for Future Reference

| File/Dir | Purpose | Delete? | Reason |
|----------|---------|---------|--------|
| `.coverage` | Coverage data | ✅ Yes | Regenerated by pytest |
| `.hypothesis/` | Test database | ✅ Yes | Regenerated by hypothesis |
| `.idea/` | IDE settings | ⚠️ Maybe | Only if you use PyCharm |
| `.pytest_cache/` | Test cache | ✅ Yes | Regenerated by pytest |
| `.ruff_cache/` | Linter cache | ✅ Yes | Regenerated by ruff |
| `__pycache__/` | Bytecode | ✅ Yes | Regenerated by Python |
| `htmlcov/` | Coverage HTML | ✅ Yes | Regenerated by pytest-cov |
| `state/` | Runtime state | ❌ No (locally) | But remove from git! |
| `docs/` | Documentation | ❌ No | Keep in git! |

---

## 🚀 After Cleanup Verification

```bash
# 1. Check git status
git status

# Expected output:
# On branch feature/phase-1-interfaces
# Changes to be committed:
#   modified:   .gitignore
#   deleted:    state/fsd_state.json
#   deleted:    state/fsd/*.json

# 2. Verify state files are ignored
echo "test" > state/test.json
git status  # Should NOT show state/test.json
rm state/test.json

# 3. Push cleanup to GitHub
git push origin feature/phase-1-interfaces
```

---

**Result**: Clean, professional codebase ready for multi-developer collaboration! ✅
