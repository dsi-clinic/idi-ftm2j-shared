"""Entry point for the idi-bootstrap Pulumi stack.

Provisions account-level AWS resources required for GitHub Actions OIDC
authentication across all repos in the dsi-clinic org, then exports their
identifiers so downstream stacks can reference them without hard-coding ARNs.

Stack outputs
-------------
oidc_provider_arn   : ARN of the GitHub Actions OIDC identity provider.
oidc_provider_url   : Issuer URL of the OIDC provider.
checks_role_arn     : ARN of the read-only role assumed on pull requests and
                      manual workflow runs.
checks_role_name    : Name of the checks role.
deploy_role_arn     : ARN of the full-deploy role assumed on main/dev/release
                      branch pushes.
deploy_role_name    : Name of the deploy role.
"""

import pulumi
from infra import iam, oidc

pulumi.export("oidc_provider_arn", oidc.oidc_provider.arn)
pulumi.export("oidc_provider_name", oidc.oidc_provider.id)

pulumi.export("checks_role_arn", iam.checks_role.arn)
pulumi.export("checks_role_name", iam.checks_role.name)
pulumi.export("deploy_role_arn", iam.deploy_role.arn)
pulumi.export("deploy_role_name", iam.deploy_role.name)
