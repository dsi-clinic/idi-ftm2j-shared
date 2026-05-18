"""EventBridge Scheduler dead-letter queue (SQS).

Captures EventBridge Scheduler invocation failures — for example, when a
scheduled ECS task cannot be launched due to capacity or IAM errors. Messages
are retained for the configured number of days so failures can be inspected
and replayed manually if needed.
"""

import pulumi_aws as aws

from . import config

# -----------------------------------------------------------------------------
# Dead-Letter Queue (SQS) — catches scheduling failures
# -----------------------------------------------------------------------------
dlq = aws.sqs.Queue(
    "idi-scheduler-dlq",
    name=f"{config.name_prefix}-scheduler-dlq",
    message_retention_seconds=config.dlq_retention_days * 86400,
    tags=config.tags({"purpose": "EventBridge Scheduler dead-letter queue"}),
)
