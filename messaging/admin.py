from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("buyer", "seller", "listing", "bundle_item", "last_message_at")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "listing" in form.base_fields:
            form.base_fields["listing"].required = obj is None
        return form


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "body_text", "is_read", "sent_at")
    list_filter = ("is_read",)
