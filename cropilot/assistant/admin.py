from django.contrib import admin

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ["role", "text", "field", "focus_field", "citations", "created_at"]
    readonly_fields = ["created_at"]
    raw_id_fields = ["field", "focus_field"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["title", "updated_at", "created_at"]
    search_fields = ["title", "messages__text"]
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["conversation", "role", "created_at", "__str__"]
    list_filter = ["role"]
    search_fields = ["text"]
    raw_id_fields = ["conversation", "field", "focus_field"]
