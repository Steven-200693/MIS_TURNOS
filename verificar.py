import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from horarios.models import Rol, Franja, Empleado

print("--- Horas semanales ---")
for r in Rol.objects.all():
    print(r.nombre, r.horas_semanales(), "h por semana")

print("\n--- Personal por franja ---")
for f in Franja.objects.all():
    n = Empleado.objects.filter(franja=f, activo=True).count()
    print(f, "->", n, "empleados")

print("\n--- Cobertura ---")
def cobertura(nombre_rol):
    horas = {h: 0 for h in range(24)}
    for f in Franja.objects.filter(rol__nombre=nombre_rol):
        for i in range(f.rol.horas_por_dia):
            horas[(f.hora_inicio.hour + i) % 24] += f.minimo_personas
    print(nombre_rol)
    print("  Sin cobertura:", [h for h, n in horas.items() if n == 0])
    print("  Con refuerzo: ", [h for h, n in horas.items() if n > 1])

cobertura("Técnico")
cobertura("Supervisor")