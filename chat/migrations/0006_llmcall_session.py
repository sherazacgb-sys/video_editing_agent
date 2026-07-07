import django.db.models.deletion
from django.db import migrations, models


def assign_llmcalls_to_sessions(apps, schema_editor):
    """
    Each LLMCall has a job_id. Assign it to the earliest ChatSession for that job.
    (Pre-session data has no way to know the exact session, so earliest is the best guess.)
    """
    LLMCall = apps.get_model('chat', 'LLMCall')
    ChatSession = apps.get_model('chat', 'ChatSession')

    job_to_session = {}
    for call in LLMCall.objects.all():
        if call.job_id not in job_to_session:
            session = ChatSession.objects.filter(job_id=call.job_id).order_by('created_at').first()
            if session:
                job_to_session[call.job_id] = session
            else:
                # No session exists for this job — create one so the FK can be satisfied.
                session = ChatSession.objects.create(job_id=call.job_id)
                job_to_session[call.job_id] = session
        call.session = job_to_session[call.job_id]
        call.save(update_fields=['session'])


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_chatsession'),
    ]

    operations = [
        # 1. Add nullable session FK so the data migration can fill it in.
        migrations.AddField(
            model_name='llmcall',
            name='session',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='llm_calls',
                to='chat.chatsession',
            ),
        ),
        # 2. Populate session for every existing LLMCall.
        migrations.RunPython(assign_llmcalls_to_sessions, migrations.RunPython.noop),
        # 3. Enforce NOT NULL now that all rows have a session.
        migrations.AlterField(
            model_name='llmcall',
            name='session',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='llm_calls',
                to='chat.chatsession',
            ),
        ),
        # 4. Drop the old job FK.
        migrations.RemoveField(
            model_name='llmcall',
            name='job',
        ),
    ]
