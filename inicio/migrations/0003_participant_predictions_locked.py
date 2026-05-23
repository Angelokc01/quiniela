from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inicio', '0002_remove_group_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='predictions_locked',
            field=models.BooleanField(default=False),
        ),
    ]
