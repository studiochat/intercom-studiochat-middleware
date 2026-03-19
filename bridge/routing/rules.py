"""Routing rules engine for matching conversations to assistants.

Supported Routing Rules
-----------------------
1. INBOX (type: "inbox")
   - Matches when conversation is assigned to a specific Intercom inbox (team)
   - Uses team_assignee_id from the webhook
   - Most common for Inbox Rules-based routing

2. ADMIN_ASSIGNMENT (type: "admin_assignment")
   - Matches when conversation is assigned to a specific admin
   - Uses admin_assignee_id from the webhook
   - Useful for routing based on manual admin assignment

3. TAG (type: "tag")
   - Matches when conversation has a specific tag
   - Uses tags from the webhook
   - Useful for routing based on Intercom workflows that add tags

Rule Matching Logic
-------------------
When an assistant has multiple routing rules, ALL rules must match (AND logic).
This allows combining conditions like "inbox X AND tag Y".

Assistants are evaluated in order - first match wins.
"""

from loguru import logger

from ..models import AssistantConfig, IntercomWebhookData, RoutingRule, RoutingRuleType


def _matches_rule(rule: RoutingRule, webhook_data: IntercomWebhookData) -> bool:
    """Check if a single routing rule matches the webhook data."""
    match rule.type:
        case RoutingRuleType.INBOX:
            return webhook_data.team_assignee_id == str(rule.inbox_id) if rule.inbox_id else False

        case RoutingRuleType.ADMIN_ASSIGNMENT:
            return webhook_data.admin_assignee_id == str(rule.admin_id) if rule.admin_id else False

        case RoutingRuleType.TAG:
            return rule.tag_name in webhook_data.tags if rule.tag_name else False

        case _:
            logger.warning("Unknown routing rule type: {}", rule.type)
            return False


def matches_all_rules(rules: list[RoutingRule], webhook_data: IntercomWebhookData) -> bool:
    """Check if ALL routing rules match the webhook data (AND logic).

    Returns True only if every rule in the list matches.
    Returns False if the rules list is empty.
    """
    if not rules:
        return False
    return all(_matches_rule(rule, webhook_data) for rule in rules)


def find_matching_assistant(
    assistants: list[AssistantConfig],
    webhook_data: IntercomWebhookData,
) -> AssistantConfig | None:
    """
    Find the first assistant whose routing rules match the webhook data.

    All routing rules for an assistant must match (AND logic).
    Assistants are evaluated in order, and the first match wins.

    Args:
        assistants: List of assistant configurations
        webhook_data: Parsed webhook data from Intercom

    Returns:
        The matching AssistantConfig, or None if no match
    """
    for assistant in assistants:
        if matches_all_rules(assistant.routing_rules, webhook_data):
            logger.info(
                "Assistant matched: playbook={}, rules={}",
                assistant.playbook_id,
                assistant.routing_rules,
            )
            return assistant

    logger.info("No assistant matched")
    return None
