"""High-level actions for interacting with Intercom conversations."""

from loguru import logger

from ..constants import DEFAULT_HANDOFF_REASON, HANDOFF_NOTE_TEMPLATE
from ..handoff_lock import is_locked, mark_handoff
from ..models import Action, ActionType, AssistantConfig
from .client import IntercomClient


class IntercomActions:
    """High-level interface for Intercom conversation actions."""

    def __init__(self, client: IntercomClient):
        """
        Initialize Intercom actions.

        Args:
            client: The Intercom client instance
        """
        self.client = client
        # Cache for tag IDs to avoid repeated lookups
        self._tag_cache: dict[str, str] = {}

    async def send_text(
        self,
        conversation_id: str,
        admin_id: str | int,
        message: str,
    ) -> None:
        """
        Send a text message to the conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin/bot ID sending the message
            message: The message content
        """
        if is_locked(conversation_id):
            logger.warning("Skipping send_text: conversation {} is in handoff", conversation_id)
            return

        logger.info("Sending text: len={}", len(message))
        await self.client.reply_to_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            message=message,
            message_type="comment",
        )

    async def send_note(
        self,
        conversation_id: str,
        admin_id: str | int,
        note: str,
        bypass_lock: bool = False,
    ) -> None:
        """
        Send a private note to the conversation (visible only to team).

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID sending the note
            note: The note content
            bypass_lock: If True, send even if conversation is in handoff (for handoff notes)
        """
        if not bypass_lock and is_locked(conversation_id):
            logger.warning("Skipping send_note: conversation {} is in handoff", conversation_id)
            return

        logger.info("Sending note: len={}", len(note))
        await self.client.reply_to_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            message=note,
            message_type="note",
        )

    async def send_image(
        self,
        conversation_id: str,
        admin_id: str | int,
        image_url: str,
    ) -> None:
        """
        Send an image to the conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID sending the image
            image_url: URL of the image to send
        """
        if is_locked(conversation_id):
            logger.warning("Skipping send_image: conversation {} is in handoff", conversation_id)
            return

        logger.info("Sending image")
        await self.client.attach_file_to_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            file_url=image_url,
        )

    async def unassign(
        self,
        conversation_id: str,
        admin_id: str | int,
    ) -> None:
        """
        Unassign the admin from the conversation.

        This removes the admin assignment while keeping any team assignment.
        Should be called before handoff/fallback to release the conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the unassignment
        """
        logger.info("Unassigning admin from conversation")
        await self.client.unassign_admin(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
        )
        logger.info("Admin unassigned successfully")

    async def assign_self(
        self,
        conversation_id: str,
        admin_id: str | int,
    ) -> None:
        """
        Assign the conversation to the specified admin (self-assignment).

        This ensures the AI admin is explicitly assigned to the conversation,
        not relying on Intercom's "self-assigned by replying" setting.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID to assign the conversation to
        """
        logger.info("Assigning conversation to admin")
        await self.client.assign_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            assignee_id=str(admin_id),
        )
        logger.info("Admin assigned successfully")

    async def add_tag(
        self,
        conversation_id: str,
        admin_id: str | int,
        tag_name: str,
    ) -> None:
        """
        Add a tag to the conversation.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the action
            tag_name: Name of the tag to add
        """
        logger.info("Adding tag: {}", tag_name)

        # Get or create the tag (with caching)
        if tag_name not in self._tag_cache:
            tag_id = await self.client.get_or_create_tag(tag_name)
            self._tag_cache[tag_name] = tag_id
        else:
            tag_id = self._tag_cache[tag_name]

        await self.client.add_tag_to_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            tag_id=tag_id,
        )

    async def transfer_to_inbox(
        self,
        conversation_id: str,
        admin_id: str | int,
        inbox_id: str | int,
    ) -> None:
        """
        Transfer the conversation to a different inbox (team).

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the transfer
            inbox_id: The target inbox (team) ID
        """
        logger.info("Transferring to inbox: {}", inbox_id)

        # Step 1: Unassign any current admin assignment
        await self.client.unassign_admin(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
        )

        # Step 2: Assign to team
        await self.client.assign_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            team_id=str(inbox_id),
        )

        logger.info("Transfer completed")

    async def assign_to_admin(
        self,
        conversation_id: str,
        admin_id: str | int,
        assignee_id: str | int,
    ) -> None:
        """
        Assign the conversation to a specific admin.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the assignment
            assignee_id: The admin ID to assign the conversation to
        """
        logger.info("Assigning to admin: {}", assignee_id)
        await self.client.assign_conversation(
            conversation_id=conversation_id,
            admin_id=str(admin_id),
            assignee_id=str(assignee_id),
        )

    async def execute_actions(
        self,
        conversation_id: str,
        admin_id: str | int,
        actions: list[Action],
        reason: str | None = None,
        bypass_lock: bool = False,
    ) -> None:
        """
        Execute a list of actions on a conversation.

        Used for handoff and fallback action sequences.

        Args:
            conversation_id: The conversation ID
            admin_id: The admin ID performing the actions
            actions: List of actions to execute
            reason: Optional reason (used in note templates)
            bypass_lock: If True, bypass handoff lock (used during handoff itself)
        """
        for action in actions:
            match action.type:
                case ActionType.ADD_TAG:
                    if action.tag_name:
                        await self.add_tag(
                            conversation_id=conversation_id,
                            admin_id=admin_id,
                            tag_name=action.tag_name,
                        )

                case ActionType.TRANSFER_TO_INBOX:
                    if action.inbox_id:
                        await self.transfer_to_inbox(
                            conversation_id=conversation_id,
                            admin_id=admin_id,
                            inbox_id=action.inbox_id,
                        )

                case ActionType.ASSIGN_TO_ADMIN:
                    if action.admin_id:
                        await self.assign_to_admin(
                            conversation_id=conversation_id,
                            admin_id=admin_id,
                            assignee_id=action.admin_id,
                        )

                case ActionType.ADD_NOTE:
                    if action.template:
                        # Replace {reason} placeholder
                        # Use "-" if no reason for language-agnostic output
                        note = action.template.replace(
                            "{reason}",
                            reason or DEFAULT_HANDOFF_REASON,
                        )
                        await self.send_note(
                            conversation_id=conversation_id,
                            admin_id=admin_id,
                            note=note,
                            # Notes from actions are blocked during handoff/fallback
                            # The handoff note is sent separately with bypass_lock=True
                        )

                case _:
                    logger.warning("Unknown action type: {}", action.type)

    async def execute_handoff(
        self,
        conversation_id: str,
        assistant: AssistantConfig,
        reason: str | None = None,
        conversation_tags: list[str] | None = None,
    ) -> None:
        """
        Execute handoff actions for an assistant.

        Always adds a handoff note first (before any configured actions),
        then executes the configured handoff actions. Supports tag-based
        branching to route handoffs to different destinations.

        Args:
            conversation_id: The conversation ID
            assistant: The assistant configuration with handoff settings
            reason: Optional reason for the handoff
            conversation_tags: Tags on the conversation for branch matching
        """
        tags = conversation_tags or []

        # Determine which actions to execute based on tags
        actions = assistant.handoff.actions  # Default actions
        matched_branch = None

        for branch in assistant.handoff.branches:
            if branch.tag in tags:
                actions = branch.actions
                matched_branch = branch.tag
                break

        logger.info(
            "Executing handoff: playbook={}, branch={}, tags={}",
            assistant.playbook_id,
            matched_branch,
            tags,
        )

        # CRITICAL: Mark conversation as locked FIRST to prevent parallel requests
        # from sending messages that would trigger self-assign
        mark_handoff(conversation_id)

        # Always add handoff note first (language-agnostic with emoji)
        handoff_note = HANDOFF_NOTE_TEMPLATE.format(reason=reason or DEFAULT_HANDOFF_REASON)
        try:
            await self.send_note(
                conversation_id=conversation_id,
                admin_id=assistant.admin_id,
                note=handoff_note,
                bypass_lock=True,  # Handoff notes are allowed
            )
        except Exception as e:
            logger.warning("Handoff note failed: {}", e)

        # Then execute configured actions (from matched branch or default)
        await self.execute_actions(
            conversation_id=conversation_id,
            admin_id=assistant.admin_id,
            actions=actions,
            reason=reason,
            bypass_lock=True,  # Handoff actions are allowed
        )

        logger.info("Handoff completed successfully")

    async def execute_fallback(
        self,
        conversation_id: str,
        assistant: AssistantConfig,
    ) -> None:
        """
        Execute fallback actions when AI is unavailable.

        Args:
            conversation_id: The conversation ID
            assistant: The assistant configuration with fallback settings
        """
        logger.info("Executing fallback: playbook={}", assistant.playbook_id)

        # CRITICAL: Mark conversation as locked to prevent parallel requests
        # from sending messages that would trigger self-assign
        mark_handoff(conversation_id)

        await self.execute_actions(
            conversation_id=conversation_id,
            admin_id=assistant.admin_id,
            actions=assistant.fallback.actions,
            reason="AI assistant unavailable",
            bypass_lock=True,  # Fallback actions are allowed
        )

        logger.info("Fallback completed successfully")
