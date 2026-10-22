from django.contrib import admin
from .models import AsignacionSemanal, Rol, Franja, Empleado, Turno, Novedad

@admin.register(Novedad)
class NovedadAdmin(admin.ModelAdmin):
    list_display = ('empleado', 'tipo', 'fecha_inicio', 'fecha_fin', 'nota' )
    list_filter = ('tipo',)


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
    list_display = ('empleado', 'fecha', 'franja', 'descanso', 'inicio', 'fin', 'remoto', 'manual', 'novedad')
    list_filter = ('fecha', 'descanso', 'franja', 'manual')


@admin.register(AsignacionSemanal)
class AsignacionSemanalAdmin(admin.ModelAdmin):
    list_display = ('lunes', 'franja', 'cantidad')
    list_filter = ('lunes', 'franja')

# Register your models here.
