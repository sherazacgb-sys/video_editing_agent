from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from videos.models import VideoJob


class Command(BaseCommand):
    help = (
        "Two-pass guest data retention: past GUEST_VIDEO_TTL_HOURS, delete a guest "
        "job's video/asset files and mark it Status.EXPIRED (row + chat kept); past "
        "the longer GUEST_CHAT_TTL_HOURS, delete the row (and its chat) entirely."
    )

    def handle(self, *args, **options):
        video_count = self._expire_videos()
        chat_count = self._delete_expired_rows()
        self.stdout.write(self.style.SUCCESS(
            f"Expired {video_count} guest video(s) (>{settings.GUEST_VIDEO_TTL_HOURS}h), "
            f"deleted {chat_count} guest job(s)+chat (>{settings.GUEST_CHAT_TTL_HOURS}h)."
        ))

    def _expire_videos(self):
        # Pass 1: clear a guest job's video/derived data once it's past the short
        # video TTL, but leave the row (and its ChatSession/ChatMessage rows) alone —
        # those are handled by _delete_expired_rows() on the longer chat TTL instead.
        cutoff = timezone.now() - timedelta(hours=settings.GUEST_VIDEO_TTL_HOURS)
        # owner__isnull=True is what makes this guest-only — a signed-in user's jobs
        # are never touched by this command. Excluding EXPIRED skips jobs already done.
        jobs = VideoJob.objects.filter(
            owner__isnull=True, created_at__lt=cutoff,
        ).exclude(status=VideoJob.Status.EXPIRED)

        count = 0
        for job in jobs:
            # Uploaded images/PDFs are video-editing material with no standalone
            # value once the video itself is gone, so they're purged with it.
            for asset in job.uploaded_assets.all():
                if asset.file:
                    asset.file.delete(save=False)
                asset.delete()
            if job.input_file:
                job.input_file.delete(save=False)
            if job.output_file:
                job.output_file.delete(save=False)
            # Transcript/assets/stage all describe the now-deleted video, so they're
            # cleared too — only the chat conversation itself survives this pass.
            job.transcript = None
            job.assets = None
            job.stage = None
            job.status = VideoJob.Status.EXPIRED
            job.save(update_fields=['input_file', 'output_file', 'transcript', 'assets', 'stage', 'status'])
            count += 1
        return count

    def _delete_expired_rows(self):
        # Pass 2: once a guest job is past the much longer chat TTL, delete the row
        # for good — cascades to UploadedAsset/ChatSession/ChatMessage/LLMCall rows.
        cutoff = timezone.now() - timedelta(hours=settings.GUEST_CHAT_TTL_HOURS)
        jobs = VideoJob.objects.filter(owner__isnull=True, created_at__lt=cutoff)

        count = 0
        for job in jobs:
            # Belt-and-suspenders: delete any files that might still be present (e.g.
            # if GUEST_CHAT_TTL_HOURS were ever set shorter than GUEST_VIDEO_TTL_HOURS).
            for asset in job.uploaded_assets.all():
                if asset.file:
                    asset.file.delete(save=False)
            if job.input_file:
                job.input_file.delete(save=False)
            if job.output_file:
                job.output_file.delete(save=False)
            job.delete()
            count += 1
        return count
