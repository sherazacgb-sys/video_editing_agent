from django.contrib import admin
from .models import VideoJob, UploadedAsset
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
    list_display = ('id', 'status', 'stage', 'created_at')
    readonly_fields = ('transcript', 'assets', 'error_message', 'created_at')
    inlines = [ChatSessionInline, UploadedAssetInline]
