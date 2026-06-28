from django.db import migrations, models


def copy_locks(apps, schema_editor):
    """Pasa el candado global anterior a los tres candados por sección."""
    Participant = apps.get_model('inicio', 'Participant')
    Participant.objects.filter(predictions_locked=True).update(
        lock_group=True, lock_awards=True, lock_bracket=True,
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inicio', '0003_participant_predictions_locked'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='lock_group',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='participant',
            name='lock_awards',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='participant',
            name='lock_bracket',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(copy_locks, noop),
        migrations.RemoveField(
            model_name='participant',
            name='predictions_locked',
        ),
    ]
