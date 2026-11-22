"""
The assistant's chat tables. Owned by Ola: the platform created this first version,
after that Ola changes them (and creates their migrations). Described in docs/interfaces.md.
"""

from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    """One chat, like a conversation in any chat app."""

    TITLE_LENGTH = 80

    title = models.CharField(max_length=TITLE_LENGTH, blank=True, help_text="The start of the first message.")
    state = models.JSONField(
        default=dict,
        blank=True,
        help_text="Assistant-internal state: pending observation draft, chunk ids shown in this conversation.",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="[UTC]")
    updated_at = models.DateTimeField(auto_now=True, help_text="[UTC] Moves forward with every new message.")

    class Meta:
        ordering = ["-updated_at"]

    @classmethod
    def title_from(cls, first_message: str) -> str:
        """A title from the first message: its first line, shortened to TITLE_LENGTH characters."""
        first_line = first_message.strip().splitlines()[0] if first_message.strip() else ""
        if len(first_line) <= cls.TITLE_LENGTH:
            return first_line
        return first_line[: cls.TITLE_LENGTH - 1].rstrip() + "…"

    def __str__(self) -> str:
        return self.title or f"Conversation {self.pk}"


class Message(models.Model):
    """One message in a conversation, from the farmer or the assistant."""

    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField(help_text="Markdown for assistant messages, plain text for user messages.")
    citations = models.JSONField(
        default=list, blank=True, help_text="List of citations (format in docs/interfaces.md). Empty for user messages."
    )
    field = models.ForeignKey(
        "core.Field",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The field selected on the map when the message was sent (user messages).",
    )
    focus_field = models.ForeignKey(
        "core.Field",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The field the answer points the map at (assistant messages).",
    )
    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text="Assistant-internal metadata: route, LLM usage, chart spec, observation draft (assistant messages).",
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="[UTC]")

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Keep the conversation's updated_at current, so the newest conversation is listed first.
        Conversation.objects.filter(pk=self.conversation_id).update(updated_at=timezone.now())

    def __str__(self) -> str:
        return f"{self.role}: {self.text[:60]}"


class Observation(models.Model):
    """
    DEPRECATED, kept EMPTY. The interim table of farmer reports before core.Observation existed.
    Its rows were moved to core.Observation (migration 0003); the assistant now writes only
    core.Observation. The table stays because the decision engine (and its tests) still read it:
    rows here would be counted twice, so nothing may write to it. Drop it together with the engine's
    adapter (engine/observations.py) once Bartek removes that.
    """

    class Category(models.TextChoices):
        DISEASE = "choroba"
        PEST = "szkodnik"
        WEEDS = "chwasty"
        DAMAGE = "uszkodzenie"
        OTHER = "inne"

    class Severity(models.TextChoices):
        LOW = "niskie"
        MEDIUM = "srednie"
        HIGH = "wysokie"

    field = models.ForeignKey("core.Field", on_delete=models.CASCADE, related_name="assistant_observations")
    date = models.DateField(help_text="The day the farmer saw it (local, demo calendar).")
    category = models.CharField(max_length=16, choices=Category.choices)
    threat = models.ForeignKey(
        "core.Threat", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="The threat, if the farmer named one that matches the crop's threats.",
    )
    severity = models.CharField(max_length=8, choices=Severity.choices, blank=True)
    note = models.TextField(help_text="The farmer's description, in their words.")
    details = models.JSONField(default=dict, blank=True, help_text="Anything else (e.g. the draft as extracted).")
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="observations"
    )
    idempotency_key = models.CharField(
        max_length=64, unique=True, help_text="Same key = same observation; prevents duplicates on a repeated 'yes'."
    )
    created_at = models.DateTimeField(auto_now_add=True, help_text="[UTC]")

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self) -> str:
        return f"{self.field} {self.date}: {self.category} {self.note[:40]}"
