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
