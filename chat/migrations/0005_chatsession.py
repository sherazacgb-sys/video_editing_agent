import django.db.models.deletion
from django.db import migrations, models


def migrate_messages_to_sessions(apps, schema_editor):
    """
    For every distinct job_id that exists in ChatMessage, create one ChatSession
    and point all messages for that job at it. Preserves chronological ordering.
    """
    ChatMessage = apps.get_model('chat', 'ChatMessage')
    ChatSession = apps.get_model('chat', 'ChatSession')

    job_to_session = {}
    for msg in ChatMessage.objects.all().order_by('created_at'):
        if msg.job_id not in job_to_session:
            # One session per job for all pre-existing messages.
            job_to_session[msg.job_id] = ChatSession.objects.create(job_id=msg.job_id)
        msg.session = job_to_session[msg.job_id]
        msg.save(update_fields=['session'])


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0004_llmcall'),
        ('videos', '0001_initial'),
    ]

    operations = [
        # 1. Create the ChatSession table.
        migrations.CreateModel(
            name='ChatSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='chat_sessions',
                    to='videos.videojob',
                )),
            ],
            options={'ordering': ['created_at']},
        ),
        # 2. Add nullable session FK so the data migration can fill it in.
        migrations.AddField(
            model_name='chatmessage',
            name='session',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='messages',
                to='chat.chatsession',
            ),
        ),
        # 3. Populate session for every existing message.
        migrations.RunPython(migrate_messages_to_sessions, migrations.RunPython.noop),
        # 4. Now all rows have a session; enforce NOT NULL.
        migrations.AlterField(
            model_name='chatmessage',
            name='session',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='messages',
                to='chat.chatsession',
            ),
        ),
        # 5. Drop the old direct job FK — session.job carries that relationship now.
        migrations.RemoveField(
            model_name='chatmessage',
            name='job',
        ),
    ]
