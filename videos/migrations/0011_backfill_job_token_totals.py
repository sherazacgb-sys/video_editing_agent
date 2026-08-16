from django.db import migrations
from django.db.models import Sum


def backfill_totals(apps, schema_editor):
    # One-off backfill for jobs that existed before total_prompt_tokens/
    # total_completion_tokens were added (0010) — mirrors chat/migrations/
    # 0010_backfill_session_token_totals.py one level up. Sums each job's
    # chat_sessions totals (already backfilled there) rather than re-aggregating
    # LLMCall directly, since ChatSession's totals are the trusted source now.
    VideoJob = apps.get_model('videos', 'VideoJob')
    for job in VideoJob.objects.all():
        totals = job.chat_sessions.aggregate(
            prompt=Sum('total_prompt_tokens'), completion=Sum('total_completion_tokens'),
        )
        job.total_prompt_tokens = totals['prompt'] or 0
        job.total_completion_tokens = totals['completion'] or 0
        job.save(update_fields=['total_prompt_tokens', 'total_completion_tokens'])


def noop_reverse(apps, schema_editor):
    # Reversing would mean zeroing the totals back out — not worth doing since
    # forward-running this migration again is idempotent and cheap.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0010_videojob_total_completion_tokens_and_more'),
        ('chat', '0010_backfill_session_token_totals'),
    ]

    operations = [
        migrations.RunPython(backfill_totals, noop_reverse),
    ]
