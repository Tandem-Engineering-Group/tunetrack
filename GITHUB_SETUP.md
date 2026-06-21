# Publish TuneTrack to GitHub

This folder is already a git repo with an initial commit. Two ways to push it to a
**private** repo under the Tandem-Engineering-Group org, then invite the team.

## Option A — GitHub CLI (fastest)

```bash
gh auth login                 # once, if not already
gh repo create Tandem-Engineering-Group/tunetrack \
  --private --source=. --remote=origin --push
```

## Option B — manual

1. On github.com, create a new **private** repo under the org:
   `Tandem-Engineering-Group/tunetrack` — do NOT add a README/license (we have them).
2. Then from this folder:

```bash
git remote add origin git@github.com:Tandem-Engineering-Group/tunetrack.git
git branch -M main
git push -u origin main
```

(Use the `https://github.com/...` URL instead of `git@` if you auth over HTTPS.)

## Invite the team

Repo → **Settings → Collaborators and teams** → add your org team (or individuals) with
**Write** access. Consider protecting `main` and using feature branches + PRs.

## Set your commit identity (optional)

The initial commit used a placeholder author. To make it yours:

```bash
git config user.name  "Richard Letts"
git config user.email "you@tandem...."
git commit --amend --reset-author --no-edit
```

## Data hygiene (already handled)

`.gitignore` keeps `tunetrack.db` and `samples/*.csv` out of the repo — logs and the
local database stay off GitHub. Drop sample CSVs in `samples/` locally; they won't be
committed.
