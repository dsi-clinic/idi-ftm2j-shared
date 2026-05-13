# idi-ftm2j-shared

Shared AWS infrastructure for the FTM2J terminal ecosystem. Two independent Pulumi stacks — deploy bootstrap first, then shared.

---

## `pulumi-bootstrap` — GitHub Actions OIDC

Provisions the account-level OIDC identity provider and the two IAM roles that all `dsi-clinic` repos use to authenticate with AWS from GitHub Actions.

> **Run locally.** This stack must be deployed from a workstation with AWS credentials — it creates the very roles that CI uses, so CI cannot deploy it itself.

```bash
cd pulumi-bootstrap
pulumi stack select dev
pulumi preview
pulumi up
```

**Roles created:**

| Role | Assumed by | Access |
|------|-----------|--------|
| `checks` | Pull requests, manual `workflow_dispatch` runs | Read-only (`pulumi preview`) |
| `deploy` | Pushes to `main`, `dev`, `release/**` | Full deploy (`pulumi up`) |

Both roles trust any repository in the `dsi-clinic` org — no updates needed when new repos are added.

---

## `pulumi` — Shared Infrastructure

Provisions the AWS resources shared across all FTM2J processor pipelines. Individual processor stacks reference these outputs rather than creating their own copies.

```bash
cd pulumi
pulumi stack select dev
pulumi preview
pulumi up
```

**Resources:**

| Resource | Description |
|----------|-------------|
| S3 bucket | Pipeline input, output, and failure storage. Encrypted at rest; retained on stack destroy to prevent data loss. |
| S3 VPC gateway endpoint | Routes S3 traffic over the private AWS network, avoiding internet egress from ECS tasks. |
| SQS dead-letter queue | Captures EventBridge Scheduler invocation failures for inspection and replay. |

**Stack outputs** consumed by downstream processor stacks:

```
processor_bucket_name
processor_bucket_arn
s3_endpoint_id
s3_endpoint_arn
dlq_url
dlq_arn
```

>`deploy.yml` is path-filtered: version/publish jobs only run when `src/**` or `pyproject.toml` changed; the Pulumi deploy job only runs when `pulumi-shared/**` changed.

---

# development + contributing

Install all dependency groups (includes `dev` tools: pytest, ruff):

```bash
uv sync --all-groups
```

## tests

```bash
uv run pytest
```

## linting + formatting

```bash
uv run ruff check .    # lint
uv run ruff format .   # format
```

## code style

| Rule | Value |
|---|---|
| Line length | 100 characters |
| Docstring convention | Google (`pydocstyle`) |
| Type annotations | Required on all public functions and classes |
| String quotes | Double-quoted (ruff `Q` ruleset) |

## branching strategy + versioning

Two-branch model with short-lived issue branches.

### long-lived branches

| Branch | Purpose      | Version style                | Deploy target |
| ------ | ------------ | ---------------------------- | ------------- |
| `dev`  | Integration  | `X.Y.Z-alphaN` (pre-release) | `dev` stack   |
| `main` | Production   | `X.Y.Z` (stable)             | `prod` stack  |

Both branches are protected. All changes occur via pull request.

### short-lived branches

- **`issue-<number>-<slug>`** — feature, bug-fix, and chore work.
    - Branch from `dev`, PR back to `dev`.
    - While the PR is open, only [`checks.yml`](../.github/workflows/checks.yml) runs (lint, tests, security, Pulumi preview). Pushes to the issue branch do not bump the version or deploy.
    - On merge, the push to `dev` triggers [`deploy.yml`](../.github/workflows/deploy.yml): bumps the alpha version and deploys the `dev` stack.
    - Note: It is best to create branches with this naming convention as you will be able to manually deploy these branches for testing in the `dev` stack. See (#manual-deploys)
- **Hotfix** — urgent production fix.
    - Branch from `main` as `issue-<number>-hotfix-<slug>`, PR back to `main`.
    - After release, merge `main` back into `dev` (see [Syncing main back into dev](#3-syncing-main-back-into-dev)).

### ci/cd pipelines

Validation and deployment are split across two workflows:

- [`checks.yml`](../.github/workflows/checks.yml) — runs on every PR, required before merge. Lint, tests, security scan, Pulumi preview.
- [`deploy.yml`](../.github/workflows/deploy.yml) — runs on push to `dev` or `main` (i.e. after a merge). Bumps version, tags, releases, deploys Pulumi, publishes to PyPI (`main` only, if the repo includes a package).

### versioning

Versions live in `pyproject.toml` and are bumped by `deploy.yml` using `uv version`.

| Trigger                          | Bump command                           | Example               |
| -------------------------------- | -------------------------------------- | --------------------- |
| Push to `dev`, no existing alpha | `uv version --bump patch --bump alpha` | `1.4.0` → `1.4.1a1`   |
| Push to `dev`, existing alpha    | `uv version --bump alpha`              | `1.4.1a1` → `1.4.1a2` |
| Push to `main`                   | `uv version --bump stable`             | `1.4.1a3` → `1.4.1`   |

Each successful deploy:

1. Commits the bumped `pyproject.toml` + `uv.lock` with `[skip ci]`.
2. Pushes a `vX.Y.Z[aN]` git tag.
3. Creates a GitHub Release — pre-release on `dev`, stable on `main`.
4. On `main`: builds the wheel/sdist and publishes to PyPI (if the repo ships a package).

### development cycle

#### 1. dev → issue → alpha release

```
                                    PR
issue-123-add-feature  ────────────────────────────────► dev
        ▲                                              │
        │ branch                                       │ push triggers deploy.yml
        │                                              ▼
       dev ◄──────────────────────────────────── 1.4.1a1, 1.4.1a2, ...
                        merge                    deployed to dev stack
```

1. `git switch dev && git pull`
2. `git switch -c issue-123-add-feature`
3. Commit, push, open PR targeting `dev`. `checks.yml` runs.
4. Merge the PR (squash recommended). The push to `dev` triggers `deploy.yml`:
   - Bumps to the next alpha (`1.4.1a1` if no alpha exists yet, otherwise increments the alpha counter).
   - Tags, creates a pre-release, deploys the `dev` Pulumi stack, publishes the image. PyPI publish is skipped.
5. More issue PRs into `dev` keep stacking alphas (`1.4.1a2`, `1.4.1a3`, …) on the same patch line until a stable release cuts that line off.

#### 2. dev → main → stable release

```
dev (1.4.1a3) ───────── PR ─────────► main
 ▲                                      │ push triggers deploy.yml
 │                                      ▼
  ◄────────────────────────────────── 1.4.1 (stable)
                sync/merge            deployed to prod stack
                                      published to PyPI
```

1. When `dev` is ready to ship, open a PR from `dev` → `main`. `checks.yml` runs against the `prod` Pulumi stack preview.
2. Review and merge. **Do not squash** — preserve the alpha history so release notes capture every change. A merge commit is fine.
3. The push to `main` triggers `deploy.yml`:
   - `uv version --bump stable` drops the `aN` suffix (`1.4.1a3` → `1.4.1`).
   - Tags `v1.4.1`, creates a stable GitHub Release, deploys the `prod` Pulumi stack, publishes to PyPI (if applicable).

#### 3. syncing main back into dev

After every stable release (and any hotfix that lands directly on `main`), merge `main` back into `dev` so `dev` stays ahead of `main` and the histories stay aligned.

```bash
git switch main && git pull
git switch dev && git pull
git merge main          # bring in the stable bump commit + any hotfixes
git push
```

The next push to `dev` produces `1.4.2a1` — a new alpha line above the just-released `1.4.1`.

On a `pyproject.toml` conflict, keep `main`'s stable version. The next `dev` deploy bumps from there.

### manual deploys

`deploy.yml` accepts `workflow_dispatch`:

- From `dev` it deploys the `dev` stack.
- From `main` it deploys the `prod` stack.

Use this to redeploy Pulumi without a code change (e.g. after rotating a secret). Version/publish jobs stay gated on `src/**` changes.

### summary

- `dev` is the only place new work lands; every merge produces an alpha.
- `main` cuts stable releases from whatever alpha `dev` is on.
- After every release on `main`, merge `main` back into `dev`.
