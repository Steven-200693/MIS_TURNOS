from django.contrib import admin
from django.urls import path

from horarios import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # Página y datos de la semana
    path('', views.index, name='index'),
    path('api/semana/', views.api_semana, name='api_semana'),
    path('api/generar/', views.api_generar, name='api_generar'),
    path(
        'api/tecnicos/distribucion/',
        views.api_distribucion_tecnicos_guardar,
        name='api_distribucion_tecnicos_guardar',
    ),
    path('api/limpiar/', views.api_limpiar_semana, name='api_limpiar_semana'),

    # Administración de personal
    path('personal/', views.personal, name='personal'),
    path('api/personal/', views.api_personal, name='api_personal'),
    path('api/empleados/guardar/', views.api_empleado_guardar, name='api_empleado_guardar'),
    path('api/roles/guardar/', views.api_rol_guardar, name='api_rol_guardar'),
    path('api/franjas/guardar/', views.api_franja_guardar, name='api_franja_guardar'),
    path('api/franjas/eliminar/', views.api_franja_eliminar, name='api_franja_eliminar'),

    # Edición manual de turnos
    path('api/turnos/descanso/', views.api_turno_descanso, name='api_turno_descanso'),
    path('api/turnos/intercambiar/', views.api_turno_intercambiar, name='api_turno_intercambiar'),
    path('api/turnos/horario/', views.api_turno_horario, name='api_turno_horario'),
    path('api/novedades/guardar/', views.api_novedad_guardar, name='api_novedad_guardar'),
    path('api/novedades/eliminar/', views.api_novedad_eliminar, name='api_novedad_eliminar'),
]