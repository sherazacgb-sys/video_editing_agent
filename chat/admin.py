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
    # is_disabled/is_over_budget shown here (read-only) so you can see at a glance which
    # sessions got locked and why — set by suspend_session / the token-budget check in
    # chat_message respectively, not edited by hand. total_*_tokens are likewise
    # read-only — maintained by LLMCallbackHandler.on_llm_end, not edited by hand.
    list_display = ('id', 'job', 'is_disabled', 'is_over_budget', 'total_prompt_tokens', 'total_completion_tokens', 'created_at')
    list_filter = ('is_disabled', 'is_over_budget')
    readonly_fields = ('created_at', 'total_prompt_tokens', 'total_completion_tokens')
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
