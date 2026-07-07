from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_owner(apps, schema_editor):
    # Pre-existing VideoJobs predate the owner field entirely, so assign them
    # to the first superuser rather than leaving them ownerless (which would
    # make them permanently inaccessible once the field becomes required).
    VideoJob = apps.get_model('videos', 'VideoJob')
    User = apps.get_model('auth', 'User')
    fallback_owner = User.objects.filter(is_superuser=True).order_by('id').first()
    if fallback_owner is not None:
        VideoJob.objects.filter(owner__isnull=True).update(owner=fallback_owner)


def noop_reverse(apps, schema_editor):
    # Nothing to undo — reversing just drops the column, handled by RemoveField.
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('videos', '0004_uploadedasset'),
    ]

    operations = [
        # Step 1: add the column as nullable so it can exist alongside old rows.
        migrations.AddField(
            model_name='videojob',
            name='owner',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='video_jobs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Step 2: fill in owners for rows created before this field existed.
        migrations.RunPython(backfill_owner, noop_reverse),
        # Step 3: now that every row has an owner, enforce it going forward.
        migrations.AlterField(
            model_name='videojob',
            name='owner',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='video_jobs',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
