from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('videos', '0002_assets'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videojob',
            name='stage',
            field=models.CharField(
                blank=True,
                choices=[
                    ('transcribed', 'Transcribed'),
                    ('captioned', 'Captioned'),
                    ('rendered', 'Rendered'),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
