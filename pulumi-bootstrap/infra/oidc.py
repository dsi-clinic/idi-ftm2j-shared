"""GitHub Actions OIDC identity provider.

Account-level resource — one per AWS account, shared by all repositories.
Protected from deletion to prevent disrupting other repos that rely on it.
"""

import pulumi_aws as aws

import pulumi

from . import config

oidc_provider = aws.iam.OpenIdConnectProvider(
    "idi-oidc-github",
    url="https://token.actions.githubusercontent.com",
    client_id_lists=["sts.amazonaws.com"],
    thumbprint_lists=[  # Ignored by AWS but required by Pulumi
        "6938fd4d98bab03faadb97b34396831e3780aea1",  # older root CA
        "1c58a3a8518e8759bf075b76b750d4f2df264fcd",  # current root CA
    ],
    tags=config.tags({"Name": f"{config.name_prefix}-oidc-github"}),
    opts=pulumi.ResourceOptions(protect=True),
)
