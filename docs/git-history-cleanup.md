# Purging `data/nursescraper.db` from git history

## Why

The daily scraper workflow used to commit `data/nursescraper.db` to `main`
on every run. The file has grown past **100 MB**, so GitHub now rejects the
push:

```
remote: error: File data/nursescraper.db is 100.18 MB; this exceeds GitHub's
file size limit of 100.00 MB
remote: error: GH001: Large files detected.
! [remote rejected] main -> main (pre-receive hook declined)
```

The workflow has been changed so it **no longer commits the DB** (it is
published as a GitHub Release asset + a workflow artifact, and Cloudflare
Pages serves the feed files under `data/feeds/`). But ~49 historical commits
still contain old copies of the DB blob, bloating the repository. This
document is the plan to remove them.

> ⚠️ **Blocked prerequisite:** the `stableotto` account is currently
> **suspended** (`remote: Your account is suspended ... error 403`). No push
> — including the force-push this rewrite requires — will succeed until
> GitHub reinstates the account. Resolve the suspension at
> <https://support.github.com> first.

## Plan (run locally once the account is unsuspended)

This rewrites history and requires a **force-push**. Coordinate first: every
collaborator will need to re-clone or hard-reset afterwards. Make a backup
clone before starting.

### 1. Back up

```bash
git clone --mirror https://github.com/stableotto/AllJobScraper.git backup-alljobscraper.git
```

### 2. Remove the DB from all history with `git-filter-repo`

`git filter-repo` is the modern, recommended tool (faster and safer than
`filter-branch`; BFG is an alternative).

```bash
pip install git-filter-repo      # or: brew install git-filter-repo

# From a fresh, full clone of the repo:
git clone https://github.com/stableotto/AllJobScraper.git
cd AllJobScraper

# Strip the DB (and the large JSON exports, if any were ever committed)
git filter-repo \
  --path data/nursescraper.db \
  --path data/jobs-export.json \
  --path data/jobs-compact.json \
  --invert-paths
```

`--invert-paths` keeps everything **except** the listed paths.

### 3. Verify the blobs are gone and the repo shrank

```bash
git rev-list --all --objects | grep nursescraper.db   # should print nothing
git count-objects -vH                                  # check size-pack
```

### 4. Re-add the remote and force-push

`git filter-repo` removes `origin` by design, so add it back:

```bash
git remote add origin https://github.com/stableotto/AllJobScraper.git
git push --force --all origin
git push --force --tags origin
```

### 5. Have collaborators re-sync

Anyone with an existing clone must re-clone, or:

```bash
git fetch origin
git reset --hard origin/main
```

### 6. (Optional) Reclaim space on GitHub

GitHub keeps old objects reachable via internal refs for a while. After the
force-push, open a support request to run server-side `gc` if the repo size
on GitHub doesn't drop.

## Notes

- The local working copy still has `data/nursescraper.db`; it is now
  `.gitignore`d so it won't be re-added.
- Release tags like `data-YYYY-MM-DD-N` and their assets are unaffected by a
  tree-history rewrite — removing the DB blob from tree history does not
  delete Release assets.
