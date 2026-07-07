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
