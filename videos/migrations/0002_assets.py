from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='videojob',
            name='captions',
        ),
        migrations.AddField(
            model_name='videojob',
            name='assets',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='videojob',
            name='stage',
            field=models.CharField(
                blank=True,
                choices=[
                    ('transcribed', 'Transcribed'),
                    ('assets_ready', 'Assets Ready'),
                    ('rendered', 'Rendered'),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
