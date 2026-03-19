"""Tests for routing logic."""

from bridge.models import (
    AssistantConfig,
    IntercomWebhookData,
    RoutingRule,
    RoutingRuleType,
)
from bridge.routing.rollout import should_route_to_assistant
from bridge.routing.rules import find_matching_assistant, matches_all_rules


class TestRoutingRules:
    """Tests for routing rule matching."""

    def test_matches_inbox_rule(self, sample_webhook_data: IntercomWebhookData):
        """Test inbox-based routing rule."""
        rules = [RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id")]

        assert matches_all_rules(rules, sample_webhook_data) is True

    def test_matches_inbox_rule_no_match(self, sample_webhook_data: IntercomWebhookData):
        """Test inbox rule when inbox doesn't match."""
        rules = [RoutingRule(type=RoutingRuleType.INBOX, inbox_id="other-inbox-id")]

        assert matches_all_rules(rules, sample_webhook_data) is False

    def test_matches_tag_rule(self, sample_webhook_data: IntercomWebhookData):
        """Test tag-based routing rule."""
        rules = [RoutingRule(type=RoutingRuleType.TAG, tag_name="existing-tag")]

        assert matches_all_rules(rules, sample_webhook_data) is True

    def test_matches_tag_rule_no_match(self, sample_webhook_data: IntercomWebhookData):
        """Test tag rule when tag doesn't exist."""
        rules = [RoutingRule(type=RoutingRuleType.TAG, tag_name="nonexistent-tag")]

        assert matches_all_rules(rules, sample_webhook_data) is False

    def test_matches_admin_assignment_rule(self):
        """Test admin assignment routing rule."""
        webhook_data = IntercomWebhookData(
            topic="conversation.user.replied",
            conversation_id="conv-123",
            admin_assignee_id="admin-456",
            tags=[],
        )
        rules = [RoutingRule(type=RoutingRuleType.ADMIN_ASSIGNMENT, admin_id="admin-456")]

        assert matches_all_rules(rules, webhook_data) is True

    def test_matches_all_rules_and_logic(self, sample_webhook_data: IntercomWebhookData):
        """Test that ALL rules must match (AND logic)."""
        # sample_webhook_data has: team_assignee_id="test-inbox-id", tags=["existing-tag"]

        # Both rules match - should return True
        rules_both_match = [
            RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id"),
            RoutingRule(type=RoutingRuleType.TAG, tag_name="existing-tag"),
        ]
        assert matches_all_rules(rules_both_match, sample_webhook_data) is True

        # First rule matches, second doesn't - should return False (AND logic)
        rules_one_fails = [
            RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id"),
            RoutingRule(type=RoutingRuleType.TAG, tag_name="nonexistent-tag"),
        ]
        assert matches_all_rules(rules_one_fails, sample_webhook_data) is False

        # First rule fails, second matches - should return False (AND logic)
        rules_first_fails = [
            RoutingRule(type=RoutingRuleType.INBOX, inbox_id="wrong-inbox"),
            RoutingRule(type=RoutingRuleType.TAG, tag_name="existing-tag"),
        ]
        assert matches_all_rules(rules_first_fails, sample_webhook_data) is False

    def test_matches_all_rules_empty_list(self, sample_webhook_data: IntercomWebhookData):
        """Test that empty rules list returns False."""
        assert matches_all_rules([], sample_webhook_data) is False

    def test_find_matching_assistant(
        self,
        sample_webhook_data: IntercomWebhookData,
        sample_assistant_config: AssistantConfig,
    ):
        """Test finding the matching assistant."""
        assistants = [sample_assistant_config]

        result = find_matching_assistant(assistants, sample_webhook_data)

        assert result is not None
        assert result.playbook_id == "test-playbook-id"

    def test_find_matching_assistant_first_match_wins(
        self,
        sample_webhook_data: IntercomWebhookData,
    ):
        """Test that the first matching assistant is returned."""
        assistants = [
            AssistantConfig(
                playbook_id="first-playbook",
                admin_id="first-admin",
                routing_rules=[RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id")],
            ),
            AssistantConfig(
                playbook_id="second-playbook",
                admin_id="second-admin",
                routing_rules=[RoutingRule(type=RoutingRuleType.INBOX, inbox_id="test-inbox-id")],
            ),
        ]

        result = find_matching_assistant(assistants, sample_webhook_data)

        assert result is not None
        assert result.playbook_id == "first-playbook"

    def test_find_matching_assistant_no_match(self, sample_webhook_data: IntercomWebhookData):
        """Test when no assistant matches."""
        assistants = [
            AssistantConfig(
                playbook_id="unmatched-playbook",
                admin_id="admin",
                routing_rules=[RoutingRule(type=RoutingRuleType.INBOX, inbox_id="other-inbox-id")],
            )
        ]

        result = find_matching_assistant(assistants, sample_webhook_data)

        assert result is None


class TestRollout:
    """Tests for rollout control."""

    def test_rollout_100_percent(self, sample_assistant_config: AssistantConfig):
        """Test 100% rollout always returns True."""
        sample_assistant_config.rollout.percentage = 100

        # Test multiple conversation IDs
        for i in range(10):
            assert should_route_to_assistant(sample_assistant_config, f"conv-{i}") is True

    def test_rollout_0_percent(self, sample_assistant_config: AssistantConfig):
        """Test 0% rollout always returns False."""
        sample_assistant_config.rollout.percentage = 0

        for i in range(10):
            assert should_route_to_assistant(sample_assistant_config, f"conv-{i}") is False

    def test_rollout_deterministic(self, sample_assistant_config: AssistantConfig):
        """Test that rollout is deterministic for the same conversation ID."""
        sample_assistant_config.rollout.percentage = 50
        conversation_id = "test-conversation-123"

        # Should return the same result every time
        first_result = should_route_to_assistant(sample_assistant_config, conversation_id)

        for _ in range(10):
            assert (
                should_route_to_assistant(sample_assistant_config, conversation_id) == first_result
            )

    def test_rollout_distribution(self, sample_assistant_config: AssistantConfig):
        """Test that rollout roughly follows the percentage."""
        sample_assistant_config.rollout.percentage = 50

        # Test with many conversation IDs
        routed_count = 0
        total = 1000

        for i in range(total):
            if should_route_to_assistant(sample_assistant_config, f"conv-{i}"):
                routed_count += 1

        # Should be roughly 50% (with some tolerance for randomness)
        percentage = (routed_count / total) * 100
        assert 40 <= percentage <= 60, f"Expected ~50%, got {percentage}%"
