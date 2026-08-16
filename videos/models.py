from django.conf import settings
from django.db import models


def _asset_upload_path(instance, filename):
    # Namespaced by job id so uploads from different jobs never collide on disk.
    return f'asset_uploads/{instance.job_id}/{filename}'


class VideoJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending'
        PROCESSING = 'processing'
        DONE = 'done'
        FAILED = 'failed'
        # Guest-only: set by purge_guest_jobs once GUEST_VIDEO_TTL_HOURS elapses — the
        # video/output files are deleted but the row (and its chat history) is kept
        # around until the longer GUEST_CHAT_TTL_HOURS purge deletes it entirely.
        EXPIRED = 'expired'

    class Stage(models.TextChoices):
        TRANSCRIBED = 'transcribed'
        CAPTIONED = 'captioned'
        RENDERED = 'rendered'

    # Owning user — null for guest-created jobs (see guest_id below). Every view must
    # filter/lookup by (pk, owner) so one account can never read, edit, or delete
    # another account's job by guessing an id.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='video_jobs',
        null=True, blank=True,
    )
    # Stand-in for `owner` on jobs created by an anonymous visitor: a random UUID
    # minted by views.continue_as_guest and stored in a cookie on their browser.
    # Mutually exclusive with owner — a job has exactly one of the two set — so a
    # guest's lookup (owner__isnull=True, guest_id=...) can never match a real
    # account's row and vice versa. purge_guest_jobs clears the video files (see
    # Status.EXPIRED) after GUEST_VIDEO_TTL_HOURS, then deletes the whole row
    # (cascading to chat) after the longer GUEST_CHAT_TTL_HOURS.
    guest_id = models.UUIDField(null=True, blank=True, db_index=True)
    # Nullable so purge_guest_jobs can clear a guest's video (see Status.EXPIRED above)
    # once GUEST_VIDEO_TTL_HOURS elapses, without deleting the row/chat history yet.
    input_file = models.FileField(upload_to='uploads/', null=True, blank=True)
    transcript = models.JSONField(null=True, blank=True)
    assets = models.JSONField(null=True, blank=True)
    output_file = models.FileField(upload_to='outputs/', null=True, blank=True)
    stage = models.CharField(max_length=20, choices=Stage.choices, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # Render progress 0–100, written by run_render's ffmpeg callback while the
    # export encodes; the job_state poll reads it so the Export button can show
    # a real progress bar. Only meaningful while status is PROCESSING on a render.
    progress = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Running totals across every chat session on this job — the same idea as
    # ChatSession.total_prompt_tokens/total_completion_tokens (chat/models.py) one
    # level up. Kept in sync via F()-expression increments in
    # LLMCallbackHandler.on_llm_end (chat/callbacks.py) so a job's all-time LLM
    # cost is readable without aggregating across chat_sessions on every request.
    total_prompt_tokens = models.PositiveIntegerField(default=0)
    total_completion_tokens = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']


class GuestFeedback(models.Model):
    # Named for its original trigger — the auto-popup prompted after a guest's
    # video reaches a meaningful result (stage CAPTIONED — see job_detail.html's
    # maybeShowFeedbackModal). A signed-in user can also submit one via the
    # header "Feedback" button (openFeedbackModal) — guest_id is just null then.
    # Kept even after purge_guest_jobs deletes the job (job FK is SET_NULL, not
    # CASCADE) since the feedback itself is still useful once the job is gone.
    job = models.ForeignKey(VideoJob, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback')
    # Copied from VideoJob.guest_id at submit time rather than read off the job
    # later, so feedback stays attributable to a guest even after job=None. Null
    # for feedback from a signed-in user (job.owner identifies them instead).
    guest_id = models.UUIDField(null=True, blank=True, db_index=True)
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class UploadedAsset(models.Model):
    # A file the user uploaded from the Assets panel — an image directly, or an
    # image rasterized from one page of an uploaded PDF (see source_pdf below).
    # Kept as its own model (not folded into VideoJob.assets) because assets is a
    # JSONField and can't hold binary file data.
    class Kind(models.TextChoices):
        IMAGE = 'image'
        PDF = 'pdf'

    job = models.ForeignKey(VideoJob, on_delete=models.CASCADE, related_name='uploaded_assets')
    file = models.FileField(upload_to=_asset_upload_path)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    original_name = models.CharField(max_length=255)
    # Set only on images generated by rasterizing a PDF page; links back to that
    # PDF's own row so the Assets panel/agent can show which file a page came from.
    source_pdf = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='pages')
    page_number = models.PositiveIntegerField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']
