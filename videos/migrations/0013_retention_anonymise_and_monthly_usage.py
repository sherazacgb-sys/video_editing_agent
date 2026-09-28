# Hand-written for the 12-month anonymisation + monthly usage totals change
# (see purge_guest_jobs). Equivalent to what makemigrations generates.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0012_guestintake'),
    ]

    operations = [
        # guest_id must be clearable when an intake row is anonymised.
        migrations.AlterField(
            model_name='guestintake',
            name='guest_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        # Marks rows purge_guest_jobs has already anonymised, so it skips them.
        migrations.AddField(
            model_name='guestintake',
            name='anonymised',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='guestfeedback',
            name='anonymised',
            field=models.BooleanField(default=False),
        ),
        # Anonymous monthly totals kept after the underlying guest data is deleted.
        migrations.CreateModel(
            name='MonthlyUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(unique=True)),
                ('guest_jobs', models.PositiveIntegerField(default=0)),
                ('transcribed', models.PositiveIntegerField(default=0)),
                ('captioned', models.PositiveIntegerField(default=0)),
                ('rendered', models.PositiveIntegerField(default=0)),
                ('failed', models.PositiveIntegerField(default=0)),
                ('chat_messages', models.PositiveIntegerField(default=0)),
                ('prompt_tokens', models.PositiveBigIntegerField(default=0)),
                ('completion_tokens', models.PositiveBigIntegerField(default=0)),
            ],
            options={
                'ordering': ['-month'],
                'verbose_name_plural': 'monthly usage',
            },
        ),
    ]
