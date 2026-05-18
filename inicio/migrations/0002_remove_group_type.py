# Generated migration to remove group_type field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inicio', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='bettinggroup',
            name='group_type',
        ),
        migrations.AlterField(
            model_name='bettinggroup',
            name='name',
            field=models.CharField(max_length=120, unique=True),
        ),
    ]
