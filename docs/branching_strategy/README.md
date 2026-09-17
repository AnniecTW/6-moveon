# Team Branching & Release Strategy

## 1. Overview

Our team uses a simple weekly branching workflow to keep development organized, reduce merge conflicts, and ensure that `main` remains stable and submission-ready.

Our branching structure is:

**`main` → `week<N>` → `feat/<topic>` / `fix/<issue>`**

Each week has one integration branch, while individual team members work on separate feature or fix branches.


### Branching Strategy Diagram

```text
main           ● (Initial) ────────────────────────────────────────────────────────● (v0.3 Tag / Submit) ──>
                \                                                                  ^
                 \                                                                / (End-of-week Merge)
week3             ● (Sprint Start) ───────────●───────────────────● (Stability) ─┘
                   \                         /                   /
                    \-- feat/models-update -/                   /
                     \                                         /
                      \------ feat/four-views-and-templates --/
                         (Peer Review: 2 approvals required)
```
---

## 2. Branch Structure

| Branch | Naming | Purpose |
| :--- | :--- | :--- |
| **Main** | `main` | Stable, production-ready code and submission releases. |
| **Weekly** | `week<N>` | Integration branch for the current week's work. |
| **Feature / Fix** | `feat/<topic>`, `fix/<issue>` | Individual tasks developed by team members. |

All weekly branches are created from `main`, and feature branches are created from the current weekly branch.

---

## 3. Development Workflow

### Step 1: Create the Weekly Branch

At the beginning of each week:

```bash
git checkout main
git pull origin main
git checkout -b week3
git push -u origin week3
```

The weekly branch becomes the shared integration branch for that week's tasks.

### Step 2: Create a Feature Branch

Each teammate creates a branch from the weekly branch for their assigned task:

```bash
git checkout week3
git pull origin week3
git checkout -b feat/add-fbv-views
```

Developers should:
- Keep commits small and focused.
- Use clear commit messages.
- Never commit .env, db.sqlite3, or temporary files.

### Step 3: Open a Pull Request

When a task is complete, the developer opens a PR targeting the weekly branch.
Before merging, the PR should be reviewed by at least two teammates and verified locally.
Basic verification includes:

```bash
python manage.py makemigrations
python manage.py migrate
python manage.py check
```

The team should also perform a quick UI and functionality check.
After approval, the feature branch is merged into the weekly branch.

## 4. Weekly Release

Before the weekly deadline, the team tests the complete `week<N>` branch to make sure that:

- New features work as expected.
- Existing functionality has not been broken.
- Migrations and application checks pass.
- The application works in both development and production settings when required.

Once the weekly branch is stable, it is merged into `main`.

```text
main
  │
  └── week3
       │
       ├── feat/task-1
       ├── feat/task-2
       └── fix/issue-1
```
After merging, the `main` branch represents the stable version of the project and can be tagged for submission when needed.

Example:

```bash
git checkout main
git pull origin main
git tag v1.2-assignment2
git push origin v1.2-assignment2
```

The next week's branch is then created from the updated `main`:

```bash
git checkout main
git checkout -b week4
```

## Key Rules

1. Do not develop directly on `main`.
2. Create feature branches from the current weekly branch.
3. Use PRs for merging feature branches.
4. Require two teammate approvals before merging.
5. Keep `main` stable and submission-ready.
6. Do not commit `.env`, database files, or temporary files.
This workflow keeps individual development isolated while giving the team a clear integration point every week.

