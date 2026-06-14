# CI — GitHub PR Gating + Branch Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the repo's fast checks as parallel GitHub Actions jobs that gate every PR to `main`, with branch protection so `main` only advances through green CI.

**Architecture:** One workflow (`.github/workflows/ci.yml`) with four independent jobs (`lint`, `toc`, `pytest`, `normalizer`) running in parallel on `pull_request` to `main`, each reusing the existing Makefile/script commands so CI ≡ local. Branch protection (set via `gh api`) requires all four checks + a PR, squash-only + linear history, no auto-merge, no required approvals (solo).

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`), Python 3.11, the existing `make`/`scripts` tooling, `gh` CLI for branch protection.

---

## Conventions for this plan

**No pytest for the workflow itself** — a CI workflow can't be meaningfully unit-tested locally. Per-task local gate: the file parses as valid YAML (`python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" <file>`) and `make lint`/the hook stay green. **Real verification is the bootstrap go-live (Task 4):** the introducing PR actually runs the four jobs, and branch-protection behavior is checked live with `gh`.

**Bootstrap order matters** (chicken-and-egg): the workflow must land on `main` via its own self-checked PR *before* branch protection can require its checks. Task 4 enforces this order. Do not enable protection in an earlier task.

**Repo:** `yossisolomon/HomeAutomationSetup` (public → free Actions). Default branch `main`. Work from `/Users/yossi_solomon/dev/HomeAutomationSetup` on branch `feat/ci-github-gating`.

---

## File structure

- `.github/workflows/ci.yml` (new) — the four-parallel-job CI workflow. Sole responsibility: run the fast checks on PRs.
- `README.md` (modify) — extend the existing `## Development` section with the PR feature-flow and a branch-protection setup block (commands + bootstrap order).
- `docs/state-of-world.md` (modify) — backlog: mark CI done, record CD as the #10-dependent follow-up.

No changes to the hook, Makefile, or `tests/` — CI reuses them.

---

## Task 1: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt
      - run: pip install -r requirements-dev.txt
      - run: make lint

  toc:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt
      - run: pip install -r requirements-dev.txt
      - name: Validate meta annotations + unique names
        run: python scripts/gen_automations_toc.py --check
      - name: ToC is up to date
        run: |
          python scripts/gen_automations_toc.py
          git diff --exit-code docs/automations.md

  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt
      - run: pip install -r requirements-dev.txt
      - run: python -m pytest tests/ -v

  normalizer:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash tests/test_normalize_nodered.sh
```

Notes for the implementer: `jq` (the normalizer's only dependency) is preinstalled on `ubuntu-latest`, so the `normalizer` job needs no setup beyond checkout. The four jobs have no `needs:` between them, so GitHub runs them concurrently.

- [ ] **Step 2: Verify the workflow is valid YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid')"`
Expected: `valid`

- [ ] **Step 3: Confirm the referenced commands exist**

Run: `grep -E '^(lint|test):' Makefile && ls scripts/gen_automations_toc.py tests/test_normalize_nodered.sh`
Expected: `lint:` and `test:` targets listed and all three paths exist (the workflow calls `make lint`, `gen_automations_toc.py`, `test_normalize_nodered.sh`).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add parallel PR checks (lint, toc, pytest, normalizer)"
```

Note: `.github/workflows/` is outside `config/`, so the pre-commit hook's yamllint (scoped to `config/*.yaml`) won't touch it; that's fine.

---

## Task 2: README — feature flow + branch-protection setup

**Files:**
- Modify: `README.md` (the `## Development` section, after the existing pre-commit-hook bullet and before `See \`docs/automation-architecture.md\``)

- [ ] **Step 1: Add the CI / PR-flow + branch-protection subsection to `README.md`**

Insert this block immediately after the line that begins `- The pre-commit hook (\`scripts/git-hooks/pre-commit\`) lints YAML, …` (the last bullet in `## Development`) and before the `See \`docs/automation-architecture.md\`` line:

```markdown

### CI + branch protection

`main` is protected: every change lands through a pull request that must pass CI.
`.github/workflows/ci.yml` runs four jobs in parallel on each PR (and on every push to
the PR branch) — `lint`, `toc`, `pytest`, `normalizer` — reusing the same `make`/script
commands as the local hook, so CI and local agree. Actions are free (public repo).

Feature flow:
```bash
git checkout -b feat/<x>        # branch off main
# ...work; the local pre-commit hook gives fast feedback...
git push -u origin feat/<x>     # opens/updates the PR; CI runs the four jobs
gh pr create                    # the merge button stays disabled until all four are green
# merge (squash) only when green AND you're satisfied — green != auto-merge
```

Direct pushes to `main` are rejected; merges are squash-only (one clean commit per
feature) with linear history. No approvals are required (solo repo) — the status checks
are the gate.

**Branch-protection setup** (re-runnable; apply *after* the CI workflow has landed on
`main` so the four checks exist — see bootstrap order below):
```bash
# squash-only merges
gh api -X PATCH repos/yossisolomon/HomeAutomationSetup \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false

# require the four checks + a PR, enforce on admins, linear history
gh api -X PUT repos/yossisolomon/HomeAutomationSetup/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["CI / lint", "CI / toc", "CI / pytest", "CI / normalizer"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

**Bootstrap order** (chicken-and-egg — a required check must exist before it can be
required): land `ci.yml` via its own PR first (a same-repo PR runs the workflow from the
PR branch, so the introducing PR is self-checked), squash-merge it, *then* run the
branch-protection commands above.
```

- [ ] **Step 2: Verify the insertion didn't break the section**

Run: `grep -n "CI + branch protection\|enforce_admins\|green != auto-merge" README.md`
Expected: all three strings present, under `## Development`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README CI feature flow + branch-protection setup"
```

---

## Task 3: Backlog update in state-of-world

**Files:**
- Modify: `docs/state-of-world.md` (the `## 7. Future Automation Backlog` list)

- [ ] **Step 1: Append two backlog entries**

Add these as new numbered items at the end of the `## 7. Future Automation Backlog` list (renumber to follow the existing last item; the list currently ends at item 10 — these become 11 and 12):

```markdown
11. ✅ **CI — GitHub PR gating** *(done — `.github/workflows/ci.yml`)* — four parallel jobs
    (`lint` / `toc` / `pytest` / `normalizer`) gate every PR to `main`; branch protection
    requires them + a PR (squash-only, linear history, no auto-merge). Makes `origin/main`
    trustworthy before blacky pulls. Spec/plan: `docs/superpowers/{specs,plans}/2026-06-14-ci-github-gating*`.
12. **CD — blacky safe auto-deploy** — poller on blacky: fetch `origin/main`, run HA
    `check_config` in the real container (where HACS integrations + `secrets.yaml` live),
    reload/rollback on result, Telegram-alert. Replaces the forgettable manual `make check`.
    **Depends on #10** (chown `config/` off root so an unattended `git pull` works).
```

- [ ] **Step 2: Verify**

Run: `grep -n "CI — GitHub PR gating\|CD — blacky safe auto-deploy" docs/state-of-world.md`
Expected: both lines present in section 7.

- [ ] **Step 3: Commit**

```bash
git add docs/state-of-world.md
git commit -m "docs: backlog — CI done, CD (depends #10) queued"
```

---

## Task 4: Bootstrap go-live (push PR → verify jobs → merge → enable protection)

> **Controller/user task — not a coding subagent.** Needs `gh` auth + repo-admin rights, and exercises the live GitHub state in a specific order. Do this only after Tasks 1–3 are committed on `feat/ci-github-gating`.

- [ ] **Step 1: Push the branch and open the introducing PR**

```bash
git push -u origin feat/ci-github-gating
gh pr create --title "ci: PR gating + branch protection" \
  --body "Adds .github/workflows/ci.yml (4 parallel jobs), README flow, backlog update. See docs/superpowers/specs/2026-06-14-ci-github-gating-design.md"
```

- [ ] **Step 2: Confirm the four jobs run in parallel and pass on this PR**

```bash
gh pr checks --watch
```
Expected: `lint`, `toc`, `pytest`, `normalizer` all appear and succeed. (Same-repo PR → the workflow from the PR branch runs, so the introducing PR is self-checked.)

- [ ] **Step 3: Squash-merge the PR**

```bash
gh pr merge --squash --delete-branch
```
Expected: one squashed commit on `main`; `origin/main` advances; branch deleted.

- [ ] **Step 4: Enable squash-only + branch protection** (now that the four checks exist on `main`)

```bash
gh api -X PATCH repos/yossisolomon/HomeAutomationSetup \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false

gh api -X PUT repos/yossisolomon/HomeAutomationSetup/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["CI / lint", "CI / toc", "CI / pytest", "CI / normalizer"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```
Expected: both calls return 200 with the protection JSON.

- [ ] **Step 5: Verify protection is live**

```bash
gh api repos/yossisolomon/HomeAutomationSetup/branches/main/protection \
  --jq '.required_status_checks.contexts, .enforce_admins.enabled, .required_linear_history.enabled'
echo "test direct push (expect rejection):"
git commit --allow-empty -m "probe: direct push should be rejected" && git push origin main; echo "push exit=$?"
# clean up the probe commit regardless of push result
git reset --hard HEAD~1
```
Expected: contexts list the four jobs; `enforce_admins` true; linear history true; the `git push origin main` is **rejected** by remote (protected branch / required checks), `push exit` non-zero.

- [ ] **Step 6: Sanity-check a red PR blocks merge** (optional, recommended once)

On a throwaway branch, introduce one failure (e.g. an automation block with no `# meta:` line) → push → open PR → confirm the `toc` job fails and the merge button is blocked. Delete the branch.

---

## Self-Review

**1. Spec coverage:**
- Parallel jobs lint/toc/pytest/normalizer, Python 3.11, reuse make/scripts → Task 1. ✓
- `toc` freshness via `git diff --exit-code` → Task 1 `toc` job. ✓
- Trigger = pull_request to main (opened/synchronize/reopened) → Task 1. ✓
- Branch protection: 4 required checks + PR, no approvals, squash-only, linear history, block direct push, enforce admins → Tasks 2 (documented) + 4 (applied). ✓
- No auto-merge (green ≠ merged) → documented in README (Task 2) + Task 4 Step 3 is a manual merge. ✓
- Bootstrap order (self-checked PR → merge → protect) → Task 4 ordering + README note. ✓
- Cost = free (public) → noted in README. ✓
- README feature flow + state-of-world backlog → Tasks 2, 3. ✓
- Out of scope (CD, check_config in CI, reviewers) → not implemented. ✓
- "Include administrators" open question → resolved to `enforce_admins: true` per spec recommendation (Tasks 2/4). ✓

**2. Placeholder scan:** No TBD/TODO. The workflow YAML, README block, gh-api payloads, and verification commands are all complete and literal. Task 4 is hardware/live (gh auth + admin), explicitly flagged — not a placeholder.

**3. Consistency:** The four job names (`lint`, `toc`, `pytest`, `normalizer`) are identical across the workflow (Task 1), the README contexts (Task 2), and the branch-protection `contexts` arrays (Tasks 2 + 4). `requirements-dev.txt`, `make lint`, `python scripts/gen_automations_toc.py`, `tests/test_normalize_nodered.sh` all match the real repo. Repo slug `yossisolomon/HomeAutomationSetup` consistent.

---

## Execution Handoff

(Filled by the controller after saving — see skill.)
