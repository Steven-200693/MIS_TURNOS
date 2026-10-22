import os
import sys
import django

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from datetime import date
from horarios.models import Empleado, Novedad, Turno
from horarios.servicios import _dias_de_semana, generar_semana, regenerar_rango

hoy = date.today()
dias = _dias_de_semana(hoy)
emp = Empleado.objects.filter(activo=True, franja__isnull=False).order_by("id").first()
generar_semana(hoy, descartar_manuales=True)


def resumen(titulo):
    turnos = {t.fecha: t for t in Turno.objects.filter(empleado=emp, fecha__in=dias)}
    celdas = []
    for d in dias:
        t = turnos.get(d)
        if t is None:
            celdas.append("-")
        elif t.novedad:
            celdas.append(t.novedad[:5])
        elif t.descanso:
            celdas.append("DESC")
        else:
            celdas.append("trab")
    horas = sum(1 for t in turnos.values() if not t.descanso and not t.novedad)
    print(f"{titulo} {' '.join(c.ljust(5) for c in celdas)}| {horas * emp.rol.horas_por_dia} h")


print(f"Empleado de prueba: {emp.nombre}  (Lun Mar Mié Jue Vie Sáb Dom)\n")
resumen("1) Sin novedades:       ")

nov = Novedad.objects.create(empleado=emp, tipo="COMPENSATORIO",
                             fecha_inicio=dias[2], fecha_fin=dias[2], nota="prueba")
avisos, semanas = regenerar_rango(nov.fecha_inicio, nov.fecha_fin)
resumen("2) Compensatorio (mié): ")
print(f"   Semanas recalculadas: {semanas} | avisos: {avisos or 'ninguno'}")

nov.delete()
regenerar_rango(dias[2], dias[2])
resumen("3) Novedad eliminada:   ")