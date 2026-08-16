from django.db import migrations
from django.db.models import Sum


def backfill_totals(apps, schema_editor):
    # One-off backfill for sessions that existed before total_prompt_tokens/
    # total_completion_tokens were added (0009) — without this, any session with
    # LLMCall history from before this migration would show 0 tokens used until
    # its next turn, understating real usage. New sessions don't need this: the
    # callback (chat/callbacks.py) keeps the totals current going forward.
    ChatSession = apps.get_model('chat', 'ChatSession')
    for session in ChatSession.objects.all():
        totals = session.llm_calls.aggregate(prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens'))
        session.total_prompt_tokens = totals['prompt'] or 0
        session.total_completion_tokens = totals['completion'] or 0
        session.save(update_fields=['total_prompt_tokens', 'total_completion_tokens'])


def noop_reverse(apps, schema_editor):
    # Reversing would mean zeroing the totals back out — not worth doing since
    # forward-running this migration again is idempotent and cheap.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0009_chatsession_total_completion_tokens_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_totals, noop_reverse),
    ]
