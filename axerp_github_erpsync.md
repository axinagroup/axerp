# AXERP Upstream Sync Setup Guide

This document describes the initial setup for syncing the AXERP fork with the upstream ERPNext repository.

## Claude Skill for Upstream Sync and Rebrand.
 The /axerp-sync skill is now installed at /Users/dzbrody/.claude/skills/axerp-sync/skill.md. Here's what it does:

  - Step 1 — Fetches the latest v16.x.x release tag from the GitHub API (confirmed v16.26.2 right now)
  - Step 2 — Checks your current AXERP version so you know how far behind you are
  - Step 3 — Runs bash scripts/sync_upstream.sh <tag>
  - Step 4 — Post-sync verification, including the critical erpnext_integrations safety check

  It also embeds the "never rebrand erpnext_integrations" rule with a fix command if modules.txt gets corrupted. You can invoke it anytime with /axerp-sync.

  *The claude skill is performing all the fuction below to update the erpnext to axerp.*
  

  ---


> **Note:** For ongoing sync operations, use `scripts/sync_upstream.sh`. See `.kiro/steering/upstream-sync.md` for the full workflow.

## Initial Repository Setup

If you have already cloned the repository and are inside the `axerp` directory, you do **not** need to clone again.

### 1. Add Frappe/ERPNext as your "Upstream" source

```bash
git remote add upstream https://github.com/frappe/erpnext.git
```

### 2. Fetch all data from the Upstream repository

```bash
git fetch upstream
```

### 3. Create and switch to the `version-16` branch

```bash
git checkout -b version-16 upstream/version-16
```

### 4. Push this new branch to your AXERP repository

```bash
git push -u origin version-16
```

## Remote Setup Summary

* **`origin`** = `https://github.com/axinagroup/axerp.git` (Your proprietary repo)
* **`upstream`** = `https://github.com/frappe/erpnext.git` (The official ERPNext upstream)

## Ongoing Sync

### 1. Get the latest v16 release tag

```bash
curl -s "https://api.github.com/repos/frappe/erpnext/releases?per_page=20" \
  | python3 -c "import sys,json; r=[x['tag_name'] for x in json.load(sys.stdin) if x['tag_name'].startswith('v16')]; print(r[0])"
```

This prints the latest tag (e.g., `v16.26.2`). Compare it to the most recent `*-axerp` tag in your repo:

```bash
git tag --sort=-version:refname | grep axerp | head -3
```

### 2. Run the sync

```bash
bash scripts/sync_upstream.sh v16.26.2
```

This script handles fetching, merging, rebranding (ERPNext → AXERP), committing, tagging as `v16.26.2-axerp`, and force-pushing to origin.

## Critical: erpnext_integrations Module — Do NOT Rebrand

The `erpnext_integrations/` module name and all related references must stay as their original ERPNext values.
Rebranding them will break plugins, apps, and DocTypes that import from this module.

The following must never be changed by `smart_rename.py` or manual edits:

- `"ERPNext Integrations"` in `modules.txt`
- `"module": "ERPNext Integrations"` in any DocType JSON file
- All `erpnext.erpnext_integrations.*` import paths

After every sync, verify `modules.txt` line 15 still reads `"ERPNext Integrations"` before pushing.

## Why Force Push

Because `git commit --amend` changes the identity of the last commit, `--force` is required to update GitHub. Since this is a proprietary fork with a single maintainer on the vendor branch, this is the standard approach for maintaining a clean history.

## Tag Safety

Using `git tag -f` ensures that re-running the script for the same version (e.g., after updating the logo) moves the tag to the newest correct commit.
