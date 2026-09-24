from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        "conversation_uid",
        "buyer",
        "seller",
        "listing",
        "last_message_at",
    )
    readonly_fields = ("conversation_uid",)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "listing" in form.base_fields:
            form.base_fields["listing"].required = obj is None
        return form


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "conversation_uid",
        "conversation",
        "sender",
        "body_text",
        "is_read",
        "sent_at",
    )
    list_filter = ("is_read",)

    @admin.display(description="Conversation ID")
    def conversation_uid(self, obj):
        return obj.conversation.conversation_uid
