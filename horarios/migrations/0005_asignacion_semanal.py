from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('horarios', '0004_turno_remoto'),
    ]

    operations = [
        migrations.CreateModel(
            name='AsignacionSemanal',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID',
                )),
                ('lunes', models.DateField()),
                ('cantidad', models.PositiveSmallIntegerField(default=0)),
                ('franja', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='horarios.franja',
                )),
            ],
            options={
                'ordering': ['lunes', 'franja__hora_inicio'],
                'unique_together': {('lunes', 'franja')},
            },
        ),
    ]
