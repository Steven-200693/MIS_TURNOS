from datetime import datetime, timedelta, date
from django.db import models


class Rol(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    horas_por_dia = models.PositiveSmallIntegerField()

    class Meta:
        verbose_name = "rol"
        verbose_name_plural = "roles"

    def horas_semanales(self):
        return self.horas_por_dia * 6   # 6 días de trabajo, 1 de descanso

    def __str__(self):
        return f"{self.nombre} ({self.horas_por_dia} h/día)"


class Franja(models.Model):
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=50)
    hora_inicio = models.TimeField()
    minimo_personas = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ['rol__nombre', 'hora_inicio']

    def hora_fin(self):
        inicio = datetime.combine(date.today(), self.hora_inicio)
        return (inicio + timedelta(hours=self.rol.horas_por_dia)).time()

    def __str__(self):
        return f"{self.rol.nombre} · {self.nombre} ({self.hora_inicio:%H:%M}-{self.hora_fin():%H:%M})"


class Empleado(models.Model):
    PREFERENCIAS = [
        ('CUALQUIERA', 'Cualquier día'),
        ('SEMANA', 'Entre semana (lun-vie)'),
        ('FINDE', 'Fin de semana (sáb-dom)'),
    ]

    nombre = models.CharField(max_length=100)
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT)
    franja = models.ForeignKey(
        Franja, on_delete=models.SET_NULL, null=True, blank=True
    )
    preferencia_descanso = models.CharField(
        max_length=10, choices=PREFERENCIAS, default='CUALQUIERA'
    )
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre


class Turno(models.Model):
    empleado = models.ForeignKey(Empleado, on_delete=models.CASCADE)
    franja = models.ForeignKey(
        Franja, on_delete=models.SET_NULL, null=True, blank=True
    )
    fecha = models.DateField()
    descanso = models.BooleanField(default=False)
    inicio = models.TimeField(null=True, blank=True)
    fin = models.TimeField(null=True, blank=True)

    class Meta:
        unique_together = ('empleado', 'fecha')

    def __str__(self):
        estado = "Descanso" if self.descanso else f"{self.inicio}-{self.fin}"
        return f"{self.empleado} · {self.fecha} · {estado}"
