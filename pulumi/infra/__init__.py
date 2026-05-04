"""Pulumi infrastructure modules for the IDI FTM2J shared stack.

Modules:
    config   — Pulumi config values, derived constants, and the tags() helper.
    network  — Default VPC lookup and S3 gateway VPC endpoint.
    storage  — Processor S3 bucket with encryption and public-access controls.
    queue    — EventBridge Scheduler dead-letter queue (SQS).
"""
