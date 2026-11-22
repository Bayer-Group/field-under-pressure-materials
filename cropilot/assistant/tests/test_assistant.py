from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assistant.models import Conversation, Message
from core.models import CropClass, Field, WeatherGrid


class ConversationTests(TestCase):
    def test_title_from_uses_the_first_line(self):
        self.assertEqual(Conversation.title_from("Why is the north field at risk?\nMore text"),
                         "Why is the north field at risk?")

    def test_title_from_shortens_long_messages(self):
        title = Conversation.title_from("word " * 50)
        self.assertEqual(len(title), Conversation.TITLE_LENGTH)
        self.assertTrue(title.endswith("…"))

    def test_title_from_empty_message(self):
        self.assertEqual(Conversation.title_from("   "), "")

    def test_messages_are_ordered_oldest_first(self):
        conversation = Conversation.objects.create(title="Test")
        Message.objects.create(conversation=conversation, role=Message.Role.USER, text="first")
        Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT, text="second")
        self.assertEqual([m.text for m in conversation.messages.all()], ["first", "second"])

    def test_new_message_moves_conversation_to_the_top(self):
        older = Conversation.objects.create(title="Older")
        Conversation.objects.create(title="Newer")
        Conversation.objects.filter(pk=older.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        Message.objects.create(conversation=older, role=Message.Role.USER, text="back again")
        self.assertEqual(list(Conversation.objects.values_list("title", flat=True)), ["Older", "Newer"])

    def test_user_messages_have_empty_citations_by_default(self):
        conversation = Conversation.objects.create()
        message = Message.objects.create(conversation=conversation, role=Message.Role.USER, text="hi")
        self.assertEqual(message.citations, [])


class MessageFieldTests(TestCase):
    def test_deleting_a_field_keeps_the_chat_history(self):
        grid = WeatherGrid.objects.create(grid_id="G1", lat=50.0, lon=19.0)
        wheat = CropClass.objects.create(code=CropClass.WHEAT, name="Wheat")
        field = Field.objects.create(
            name="North field", geometry={}, area_ha=1, centroid_lat=50, centroid_lon=19,
            weather_grid=grid, h3_cells=[], crop=wheat,
        )
        conversation = Conversation.objects.create()
        message = Message.objects.create(
            conversation=conversation, role=Message.Role.ASSISTANT, text="Look here", field=field, focus_field=field
        )
        field.delete()
        message.refresh_from_db()
        self.assertIsNone(message.field)
        self.assertIsNone(message.focus_field)


class AssistantAdminTests(TestCase):
    def test_admin_pages_render(self):
        user = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        self.client.force_login(user)
        conversation = Conversation.objects.create(title="Test")
        Message.objects.create(conversation=conversation, role=Message.Role.USER, text="hi")
        for url in (
            reverse("admin:assistant_conversation_changelist"),
            reverse("admin:assistant_conversation_change", args=[conversation.pk]),
            reverse("admin:assistant_message_changelist"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
