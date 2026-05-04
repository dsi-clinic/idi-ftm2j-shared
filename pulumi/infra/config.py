"""Pulumi configuration and shared constants.

Reads stack config under the "idi" namespace and exposes derived values used
by every other module:

    name_prefix   — "{project}-{stack}-{app_name}", used as a prefix for all
                    resource names to keep them unique across stacks.
    bucket_name   — Full S3 bucket name: "{name_prefix}-{bucket_name config}".
    aws_region    — AWS region from the "aws" config namespace.
    caller        — Current AWS account identity (account ID, ARN, user ID).
    tags()        — Returns a dict of standard tags to apply to every resource.
"""

import pulumi_aws as aws

import pulumi

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
config = pulumi.Config("idi")
project_name = pulumi.get_project()
stack_name = pulumi.get_stack()
app_name = config.get("app_name") or "ftm2j-shared"
name_prefix = f"{project_name}-{stack_name}-{app_name}"
bucket_name = f"{name_prefix}-{config.require('bucket_name')}"

# AWS
aws_config = pulumi.Config("aws")
aws_region = aws_config.require("region")
caller = aws.get_caller_identity()


def tags(extra: dict | None = None) -> dict:
    """Common resource tags."""
    t = {
        "project": project_name,
        "environment": stack_name,
        "managed_by": "Pulumi",
        "app_name": app_name,
    }
    if extra:
        t.update(extra)
    return t
