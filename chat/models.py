from django.db import models

from videos.models import VideoJob


class LLMCall(models.Model):
    # Raw log of every LLM round-trip; scoped to a session so you can see
    # exactly which conversation triggered each API call.
    session = models.ForeignKey('ChatSession', on_delete=models.CASCADE, related_name='llm_calls')
    input_messages = models.JSONField()
    output_content = models.TextField()
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class ChatSession(models.Model):
    # One session = one conversation thread on a job. A job can have many sessions;
    # "New Chat" creates a fresh one while leaving older ones intact in the DB.
    job = models.ForeignKey(VideoJob, on_delete=models.CASCADE, related_name='chat_sessions')
    created_at = models.DateTimeField(auto_now_add=True)
    # Locked by the agent's own suspend_session tool after repeated attempts to bypass
    # its scope rules (see chat/agent.py) — once true, chat_message rejects further
    # messages in this session and the user must start a New Chat to keep going.
    is_disabled = models.BooleanField(default=False)
    # Locked by chat_message once this session's cumulative LLMCall token usage
    # crosses settings.CHAT_SESSION_TOKEN_BUDGET. Kept separate from is_disabled
    # (policy violation) so the two lock reasons stay distinguishable.
    is_over_budget = models.BooleanField(default=False)
    # Running totals mirrored from LLMCall rows via F()-expression increments in
    # LLMCallbackHandler.on_llm_end (chat/callbacks.py) — cached here so the budget
    # check and usage indicator don't need an aggregate() over llm_calls on every request.
    total_prompt_tokens = models.PositiveIntegerField(default=0)
    total_completion_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['created_at']


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user'
        ASSISTANT = 'assistant'
        TOOL_CALL = 'tool_call'      # agent decided to call a tool
        TOOL_RESULT = 'tool_result'  # result returned by the tool

    # Scoped to a session so history only covers the current conversation thread.
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=Role.choices)
    tool_name = models.CharField(max_length=100, blank=True, null=True)
    content = models.TextField()
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
