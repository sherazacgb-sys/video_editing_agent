from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from chat.models import ChatMessage
from videos.models import GuestFeedback, GuestIntake, MonthlyUsage, VideoJob


def _month_start(dt):
    # First instant of dt's month in local time. Used both as the MonthlyUsage key
    # and as the coarsened timestamp on anonymised rows (an exact time narrows down
    # who submitted a row; the month alone doesn't).
    return timezone.localtime(dt).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _add_usage(created_at, **counts):
    # Atomically add counts to the MonthlyUsage row for created_at's month. F()
    # increments so two overlapping purge runs can't lose each other's counts.
    increments = {field: F(field) + value for field, value in counts.items() if value}
    month = _month_start(created_at).date()
    # Row is created even when every count is zero, so a quiet month still shows up
    # in the table as a month with no activity rather than a gap.
    MonthlyUsage.objects.get_or_create(month=month)
    if increments:  # update() with no fields would raise
        MonthlyUsage.objects.filter(month=month).update(**increments)


class Command(BaseCommand):
    help = (
        "Guest data retention, meant to run hourly from cron. Pass 1: past "
        "GUEST_VIDEO_TTL_HOURS, delete a guest job's files and mark it EXPIRED. "
        "Pass 2: past GUEST_CHAT_TTL_HOURS, delete the row and its chat. Pass 3: past "
        "GUEST_ANONYMISE_AFTER_DAYS, anonymise guest intake answers and feedback. "
        "Passes 1-2 record anonymous monthly totals (MonthlyUsage) before deleting."
    )

    def handle(self, *args, **options):
        video_count = self._expire_videos()
        chat_count = self._delete_expired_rows()
        anon_count = self._anonymise_old_records()
        self.stdout.write(self.style.SUCCESS(
            f"Expired {video_count} guest video(s) (>{settings.GUEST_VIDEO_TTL_HOURS}h), "
            f"deleted {chat_count} guest job(s)+chat (>{settings.GUEST_CHAT_TTL_HOURS}h), "
            f"anonymised {anon_count} intake/feedback row(s) (>{settings.GUEST_ANONYMISE_AFTER_DAYS}d)."
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
            # Record the job in the monthly totals now, while stage/status still say
            # how far it got — they are wiped just below. Each job passes here once
            # (EXPIRED is excluded above), so it is counted exactly once.
            _add_usage(
                job.created_at,
                guest_jobs=1,
                transcribed=int(job.stage == VideoJob.Stage.TRANSCRIBED),
                captioned=int(job.stage == VideoJob.Stage.CAPTIONED),
                rendered=int(job.stage == VideoJob.Stage.RENDERED),
                failed=int(job.status == VideoJob.Status.FAILED),
            )
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
            # Chat totals are recorded here rather than in pass 1 because the chat can
            # keep going after the video expires; by now it can no longer grow.
            _add_usage(
                job.created_at,
                chat_messages=ChatMessage.objects.filter(session__job=job).count(),
                prompt_tokens=job.total_prompt_tokens,
                completion_tokens=job.total_completion_tokens,
            )
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

    def _anonymise_old_records(self):
        # Pass 3: past GUEST_ANONYMISE_AFTER_DAYS, strip everything that could point at
        # a person from intake answers and feedback, and keep the rest for trends.
        # Anonymised instead of deleted because anonymous data is outside UK GDPR's
        # storage limit, so year-on-year numbers can be kept indefinitely.
        cutoff = timezone.now() - timedelta(days=settings.GUEST_ANONYMISE_AFTER_DAYS)
        count = 0

        # Intake: drop the guest id (links rows to one visitor) and the free-text use
        # case (people write names/companies in it). Kept: referral source, the
        # looking-for-an-engineer answer, and the month.
        for row in GuestIntake.objects.filter(created_at__lt=cutoff, anonymised=False):
            # queryset.update() rather than save(): bypasses auto_now_add so the
            # coarsened month actually sticks.
            GuestIntake.objects.filter(pk=row.pk).update(
                guest_id=None, use_case='', created_at=_month_start(row.created_at), anonymised=True,
            )
            count += 1

        # Feedback: drop the guest id, the job link (a signed-in user's job names its
        # owner) and the free-text comment. Kept: the star rating and the month.
        for row in GuestFeedback.objects.filter(created_at__lt=cutoff, anonymised=False):
            GuestFeedback.objects.filter(pk=row.pk).update(
                guest_id=None, job=None, comment='', created_at=_month_start(row.created_at), anonymised=True,
            )
            count += 1
        return count
