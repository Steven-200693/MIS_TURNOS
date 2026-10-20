from django.contrib import admin
from .models import Rol, Franja, Empleado, Turno


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'horas_por_dia')


@admin.register(Franja)
class FranjaAdmin(admin.ModelAdmin):
    list_display = ('rol', 'nombre', 'hora_inicio', 'minimo_personas')
    list_filter = ('rol',)


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'rol', 'franja', 'preferencia_descanso', 'activo')
    list_filter = ('rol', 'franja', 'activo')
    search_fields = ('nombre',)


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ('empleado', 'fecha', 'franja', 'descanso', 'inicio', 'fin')
    list_filter = ('fecha', 'descanso', 'franja')

# Register your models here.
