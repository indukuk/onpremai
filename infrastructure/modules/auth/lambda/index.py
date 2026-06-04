"""
Pre-token generation Lambda trigger for Cognito.

Injects custom claims (tenant_id, role) into the JWT access token
so that downstream services can extract tenant context without
additional lookups.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Cognito Pre Token Generation trigger.

    Reads custom:tenant_id and custom:role from user attributes
    and injects them as custom claims in the access token.
    """
    logger.info(
        "Pre-token generation triggered for user: %s",
        event.get("userName", "unknown"),
    )

    user_attributes = event.get("request", {}).get("userAttributes", {})

    tenant_id = user_attributes.get("custom:tenant_id", "")
    role = user_attributes.get("custom:role", "viewer")

    if not tenant_id:
        logger.error(
            "User %s missing custom:tenant_id attribute",
            event.get("userName", "unknown"),
        )
        raise ValueError("User must have a tenant_id attribute")

    # Inject claims into the access token
    event["response"] = {
        "claimsOverrideDetails": {
            "claimsToAddOrOverride": {
                "custom:tenant_id": tenant_id,
                "custom:role": role,
            },
            "claimsToSuppress": [],
        }
    }

    logger.info(
        "Injected claims for user %s: tenant_id=%s, role=%s",
        event.get("userName", "unknown"),
        tenant_id,
        role,
    )

    return event
