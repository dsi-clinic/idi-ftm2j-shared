"""VPC lookup and S3 gateway VPC endpoint.

Looks up the account's default VPC and all of its route tables, then creates
an S3 gateway endpoint attached to those route tables. The gateway endpoint
routes S3 traffic over the private AWS network at no cost, avoiding internet
egress for S3 reads/writes from ECS tasks running in the VPC.
"""

import pulumi_aws as aws

from . import config

# -----------------------------------------------------------------------------
# Default VPC
# -----------------------------------------------------------------------------
default_vpc = aws.ec2.get_vpc(default=True)
default_vpc_route_tables = aws.ec2.get_route_tables(
    filters=[aws.ec2.GetRouteTablesFilterArgs(name="vpc-id", values=[default_vpc.id])],
)

# -----------------------------------------------------------------------------
# S3 VPC Endpoint
# -----------------------------------------------------------------------------
s3_endpoint = aws.ec2.VpcEndpoint(
    "idi-endpoint-s3",
    vpc_id=default_vpc.id,
    service_name=f"com.amazonaws.{config.aws_region}.s3",
    vpc_endpoint_type="Gateway",
    route_table_ids=default_vpc_route_tables.ids,
    tags=config.tags({"Name": f"{config.name_prefix}-endpoint-s3", "service": "s3"}),
)
