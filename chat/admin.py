from django.contrib import admin
from .models import ChatMessage, ChatSession, LLMCall


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    can_delete = False
    readonly_fields = ('role', 'tool_name', 'content', 'prompt_tokens', 'completion_tokens', 'created_at')
    fields = ('role', 'tool_name', 'prompt_tokens', 'completion_tokens', 'content', 'created_at')
    ordering = ('created_at',)


class LLMCallInline(admin.StackedInline):
    model = LLMCall
    extra = 0
    can_delete = False
    readonly_fields = ('input_messages', 'output_content', 'prompt_tokens', 'completion_tokens', 'created_at')
    fields = ('created_at', 'prompt_tokens', 'completion_tokens', 'input_messages', 'output_content')
    ordering = ('created_at',)
    verbose_name = "LLM Call"
    verbose_name_plural = "LLM Calls"


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'job', 'created_at')
    readonly_fields = ('created_at',)
    # Both messages and raw LLM calls are visible inside a session.
    inlines = [ChatMessageInline, LLMCallInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'tool_name', 'created_at')
    list_filter = ('role',)
    readonly_fields = ('created_at',)


@admin.register(LLMCall)
class LLMCallAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'prompt_tokens', 'completion_tokens', 'created_at')
    readonly_fields = ('session', 'input_messages', 'output_content', 'prompt_tokens', 'completion_tokens', 'created_at')
