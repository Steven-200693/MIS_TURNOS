from datetime import datetime, timedelta, date
from django.db import models
from django.core.exceptions import ValidationError

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

    def clean(self):
        if self.franja and self.franja.rol_id != self.rol_id:
            raise ValidationError(
                "La franja elegida no pertenece al rol de este empleado."
            )

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
    remoto = models.BooleanField(default=False)
    manual = models.BooleanField(default=False)   # ← NUEVA
    novedad = models.CharField(max_length=15, blank=True, default='')   # ← NUEVA

    class Meta:
        unique_together = ('empleado', 'fecha')

    def __str__(self):
        estado = "Descanso" if self.descanso else f"{self.inicio}-{self.fin}"
        return f"{self.empleado} · {self.fecha} · {estado}"


class AsignacionSemanal(models.Model):
    lunes = models.DateField()
    franja = models.ForeignKey(Franja, on_delete=models.CASCADE)
    cantidad = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ('lunes', 'franja')
        ordering = ['lunes', 'franja__hora_inicio']

    def __str__(self):
        return f"{self.lunes} · {self.franja} · {self.cantidad} técnicos"


class Novedad(models.Model):
    TIPOS = [
        ('COMPENSATORIO', 'Descanso compensatorio'),
        ('INCAPACIDAD', 'Incapacidad'),
        ('VACACIONES', 'Vacaciones'),
        ('PERMISO', 'Permiso'),
    ]

    empleado = models.ForeignKey(Empleado, on_delete=models.CASCADE)
    tipo = models.CharField(max_length=15, choices=TIPOS)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-fecha_inicio']
        verbose_name = "novedad"
        verbose_name_plural = "novedades"

    def clean(self):
        if isinstance(self.fecha_inicio, date) and isinstance(self.fecha_fin, date):
            if self.fecha_fin < self.fecha_inicio:
                raise ValidationError('La fecha final no puede ser anterior a la inicial.')
            if (self.fecha_fin - self.fecha_inicio).days > 365:
                raise ValidationError('Una novedad no puede durar más de un año.')

    def __str__(self):
        return f"{self.empleado} · {self.get_tipo_display()} · {self.fecha_inicio} a {self.fecha_fin}"
