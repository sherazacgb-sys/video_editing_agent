from django.contrib import admin
from .models import VideoJob, UploadedAsset, GuestFeedback
from chat.models import ChatSession


class ChatSessionInline(admin.TabularInline):
    # Shows how many chat sessions this job has; click through to see messages + LLM calls.
    model = ChatSession
    extra = 0
    can_delete = False
    readonly_fields = ('id', 'created_at')
    fields = ('id', 'created_at')
    ordering = ('created_at',)
    verbose_name = "Chat Session"
    verbose_name_plural = "Chat Sessions"
    show_change_link = True


class UploadedAssetInline(admin.TabularInline):
    # Shows uploaded images/PDFs (and rasterized PDF pages) attached to this job.
    model = UploadedAsset
    fk_name = 'job'
    extra = 0
    can_delete = True
    readonly_fields = ('kind', 'original_name', 'page_number', 'uploaded_at')
    fields = ('kind', 'original_name', 'page_number', 'uploaded_at')
    ordering = ('uploaded_at',)
    verbose_name = "Uploaded Asset"
    verbose_name_plural = "Uploaded Assets"


@admin.register(VideoJob)
class VideoJobAdmin(admin.ModelAdmin):
    # total_*_tokens are read-only here — maintained by LLMCallbackHandler.on_llm_end
    # (chat/callbacks.py), same as ChatSession's, one level up.
    list_display = ('id', 'status', 'stage', 'total_prompt_tokens', 'total_completion_tokens', 'created_at')
    readonly_fields = ('transcript', 'assets', 'error_message', 'created_at', 'total_prompt_tokens', 'total_completion_tokens')
    inlines = [ChatSessionInline, UploadedAssetInline]


@admin.register(GuestFeedback)
class GuestFeedbackAdmin(admin.ModelAdmin):
    # Read-only browse list — feedback is submitted once by a guest and never
    # edited afterward, so there's nothing for an admin to change here.
    list_display = ('id', 'rating', 'guest_id', 'job', 'created_at')
    list_filter = ('rating',)
    readonly_fields = ('job', 'guest_id', 'rating', 'comment', 'created_at')
