import json
from datetime import date, datetime, timedelta
from functools import wraps

from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import AsignacionSemanal, Empleado, Franja, Novedad, Rol, Turno
from .servicios import (
    CambioInvalido, CoberturaInsuficiente, cambiar_descansos, cambiar_horario,
    _asignaciones_fin_de_semana, distribucion_tecnicos_semana, generar_semana,
    intercambiar_descansos, lunes_de, regenerar_rango,
)

# ===============================================================
# PARTE 1: Página principal y datos de la semana
# ===============================================================

def _leer_fecha(texto):
    """Convierte '2026-10-21' en fecha. Sin texto usa hoy. Si es inválido, devuelve None."""
    if not texto:
        return date.today()
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


@ensure_csrf_cookie
def index(request):
    es_admin = request.user.is_authenticated and request.user.is_staff
    return render(request, 'horarios/index.html', {'es_admin': es_admin})


@require_GET
def api_semana(request):
    fecha = _leer_fecha(request.GET.get('fecha'))
    if fecha is None:
        return JsonResponse({'error': 'Fecha inválida. Usa el formato AAAA-MM-DD.'}, status=400)

    lunes = lunes_de(fecha)
    dias = [lunes + timedelta(days=i) for i in range(7)]
    asignaciones_fin_de_semana, _ = _asignaciones_fin_de_semana(lunes)
    franjas_tecnicos, tecnicos_sin_franja, cupos, configurada, config_invalida = (
        distribucion_tecnicos_semana(lunes)
    )

    # Una sola consulta para todos los turnos de la semana
    turnos_por_empleado = {}
    for t in Turno.objects.filter(fecha__in=dias).select_related('franja'):
        turnos_por_empleado.setdefault(t.empleado_id, {})[t.fecha.isoformat()] = {
            'descanso': t.descanso,
            'inicio': t.inicio.strftime('%H:%M') if t.inicio else None,
            'fin': t.fin.strftime('%H:%M') if t.fin else None,
            'franja': t.franja.nombre if t.franja else None,
            'remoto': t.remoto,
            'manual': t.manual,          # ← la línea nueva de la Etapa 7
            'novedad': t.novedad,        # ← la línea nueva de la Etapa 7
        }

    empleados = []
    consulta = (Empleado.objects.filter(activo=True)
                .select_related('rol', 'franja')
                .order_by('rol__nombre', 'franja__hora_inicio', 'nombre'))
    for e in consulta:
        turnos = turnos_por_empleado.get(e.id, {})
        horas_semana = 0
        for turno in turnos.values():
            if turno['inicio'] and turno['fin'] and not turno['descanso'] and not turno['novedad']:
                inicio = datetime.strptime(turno['inicio'], '%H:%M')
                fin = datetime.strptime(turno['fin'], '%H:%M')
                duracion = (fin - inicio).total_seconds() / 3600
                horas_semana += duracion if duracion > 0 else duracion + 24

        novedades = sum(1 for turno in turnos.values() if turno['novedad'])
        if e.id in asignaciones_fin_de_semana:
            dia_cobertura = asignaciones_fin_de_semana[e.id]
            horas_meta = sum(
                e.rol.horas_por_dia
                for dia in range(5)
                if not turnos.get(dias[dia].isoformat(), {}).get('novedad')
            )
            if dia_cobertura is not None and not turnos.get(
                dias[dia_cobertura].isoformat(), {}
            ).get('novedad'):
                horas_meta += 12
        else:
            horas_meta = max(0, 6 - novedades) * e.rol.horas_por_dia
        empleados.append({
            'id': e.id,
            'nombre': e.nombre,
            'rol': e.rol.nombre,
            'franja': next(
                (turnos[d.isoformat()]['franja'] for d in dias
                 if d.isoformat() in turnos and turnos[d.isoformat()]['franja']),
                e.franja.nombre if e.franja else None,
            ),
            'horas_dia': e.rol.horas_por_dia,
            'horas_semana': horas_semana,
            'horas_meta': horas_meta,
            'turnos': turnos,
        })

    return JsonResponse({
        'lunes': lunes.isoformat(),
        'dias': [d.isoformat() for d in dias],
        'empleados': empleados,
        'distribucion_tecnicos': {
            'total': len(tecnicos_sin_franja),
            'configurada': configurada,
            'invalida': config_invalida,
            'franjas': [
                {
                    'id': franja.id,
                    'nombre': franja.nombre,
                    'hora_inicio': franja.hora_inicio.strftime('%H:%M'),
                    'cantidad': cupos.get(franja.id, 0),
                    'cantidad_minima': (
                        max(
                            0,
                            2 - Empleado.objects.filter(
                                activo=True, franja=franja
                            ).count(),
                        )
                        if franja.hora_inicio.strftime('%H:%M') == '16:00'
                        else 0
                    ),
                }
                for franja in franjas_tecnicos
            ],
        },
    })


# ===============================================================
# PARTE 2: Herramientas de seguridad y guardado (Etapa 6)
# ===============================================================

def solo_staff(vista):
    """Decorador: solo deja pasar a administradores con sesión iniciada."""
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_staff):
            return JsonResponse(
                {'error': 'Debes iniciar sesión como administrador en /admin/.'},
                status=403,
            )
        return vista(request, *args, **kwargs)
    return envoltura


def _leer_json(request):
    """Convierte el cuerpo de la petición en un diccionario. Devuelve None si es inválido."""
    try:
        datos = json.loads(request.body)
    except (ValueError, TypeError):
        return None
    return datos if isinstance(datos, dict) else None


def _guardar(request, modelo, campos, validar=None):
    """Crea o edita un registro. Si viene 'id' edita, si no, crea."""
    datos = _leer_json(request)
    if datos is None:
        return JsonResponse({'error': 'Los datos enviados no son válidos.'}, status=400)

    pk = datos.get('id')
    if pk:
        objeto = modelo.objects.filter(pk=pk).first()
        if objeto is None:
            return JsonResponse({'error': 'Ese registro ya no existe.'}, status=404)
    else:
        objeto = modelo()

    for campo in campos:
        if campo in datos:
            valor = datos[campo]
            if isinstance(valor, str):
                valor = valor.strip()
            setattr(objeto, campo, valor)

    try:
        objeto.full_clean()
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)

    if validar:
        mensaje = validar(objeto)
        if mensaje:
            return JsonResponse({'error': mensaje}, status=400)

    objeto.save()
    return JsonResponse({'ok': True, 'id': objeto.pk})


# ===============================================================
# PARTE 3: Administración de personal, franjas y roles (Etapa 6)
# ===============================================================

@staff_member_required
@ensure_csrf_cookie
def personal(request):
    return render(request, 'horarios/personal.html')


@require_GET
@solo_staff
def api_personal(request):
    roles = [
        {'id': r.id, 'nombre': r.nombre, 'horas_por_dia': r.horas_por_dia,
         'horas_semana': r.horas_semanales()}
        for r in Rol.objects.order_by('nombre')
    ]

    franjas = [
        {'id': f.id, 'rol_id': f.rol_id, 'rol': f.rol.nombre, 'nombre': f.nombre,
         'hora_inicio': f.hora_inicio.strftime('%H:%M'),
         'hora_fin': f.hora_fin().strftime('%H:%M'),
         'minimo_personas': f.minimo_personas, 'activos': f.activos}
        for f in Franja.objects.select_related('rol').annotate(
            activos=Count('empleado', filter=Q(empleado__activo=True))
        )
    ]

    empleados = [
        {'id': e.id, 'nombre': e.nombre, 'rol_id': e.rol_id, 'rol': e.rol.nombre,
         'franja_id': e.franja_id, 'franja': e.franja.nombre if e.franja else None,
         'preferencia_descanso': e.preferencia_descanso, 'activo': e.activo}
        for e in Empleado.objects.select_related('rol', 'franja').order_by(
            '-activo', 'rol__nombre', 'franja__hora_inicio', 'nombre'
        )
    ]

    novedades = [
        {'id': n.id, 'empleado_id': n.empleado_id, 'empleado': n.empleado.nombre,
         'tipo': n.tipo, 'tipo_texto': n.get_tipo_display(),
         'fecha_inicio': n.fecha_inicio.isoformat(),
         'fecha_fin': n.fecha_fin.isoformat(), 'nota': n.nota}
        for n in Novedad.objects.select_related('empleado')[:200]
    ]
    tipos_novedad = [{'valor': v, 'texto': t} for v, t in Novedad.TIPOS]

    return JsonResponse({'roles': roles, 'franjas': franjas, 'empleados': empleados,
                         'novedades': novedades, 'tipos_novedad': tipos_novedad})


def _validar_rol(rol):
    if not 1 <= rol.horas_por_dia <= 12:
        return 'Las horas por día deben estar entre 1 y 12.'
    return None


@require_POST
@solo_staff
def api_empleado_guardar(request):
    return _guardar(
        request, Empleado,
        ['nombre', 'rol_id', 'franja_id', 'preferencia_descanso', 'activo'],
    )


@require_POST
@solo_staff
def api_rol_guardar(request):
    return _guardar(request, Rol, ['nombre', 'horas_por_dia'], validar=_validar_rol)


@require_POST
@solo_staff
def api_franja_guardar(request):
    return _guardar(
        request, Franja,
        ['rol_id', 'nombre', 'hora_inicio', 'minimo_personas'],
    )


@require_POST
@solo_staff
def api_franja_eliminar(request):
    datos = _leer_json(request)
    if datos is None or not datos.get('id'):
        return JsonResponse({'error': 'Falta indicar qué franja eliminar.'}, status=400)

    franja = Franja.objects.filter(pk=datos['id']).first()
    if franja is None:
        return JsonResponse({'error': 'Esa franja ya no existe.'}, status=404)

    activos = franja.empleado_set.filter(activo=True).count()
    if activos:
        return JsonResponse({
            'error': f'No se puede eliminar: tiene {activos} empleado(s) activo(s). '
                     'Muévelos a otra franja primero.'
        }, status=400)

    franja.delete()
    return JsonResponse({'ok': True})


# ===============================================================
# PARTE 4: Generar turnos y edición manual (Etapa 7)
# ===============================================================

@require_POST
@solo_staff
def api_generar(request):
    fecha = _leer_fecha(request.POST.get('fecha'))
    if fecha is None:
        return JsonResponse({'error': 'Fecha inválida. Usa el formato AAAA-MM-DD.'}, status=400)

    descartar = request.POST.get('descartar') == '1'
    lunes = lunes_de(fecha)
    manuales = 0
    if not descartar:
        manuales = (Turno.objects
                    .filter(fecha__range=(lunes, lunes + timedelta(days=6)), manual=True)
                    .values('empleado').distinct().count())

    avisos = generar_semana(fecha, descartar_manuales=descartar)
    return JsonResponse({'ok': True, 'avisos': avisos, 'manuales': manuales})


@require_POST
@solo_staff
def api_distribucion_tecnicos_guardar(request):
    datos = _leer_json(request)
    if datos is None:
        return JsonResponse({'error': 'Los datos enviados no son válidos.'}, status=400)

    fecha = _fecha_estricta(datos.get('fecha'))
    distribucion = datos.get('distribucion')
    if fecha is None or not isinstance(distribucion, list):
        return JsonResponse(
            {'error': 'Indica la semana y los cupos por franja.'},
            status=400,
        )

    lunes = lunes_de(fecha)
    franjas, tecnicos, _, _, _ = distribucion_tecnicos_semana(lunes)
    if len(franjas) != 4 or {
        franja.hora_inicio.strftime('%H:%M') for franja in franjas
    } != {'06:00', '13:00', '16:00', '23:00'}:
        return JsonResponse(
            {'error': 'Se requieren las franjas técnicas de 06:00, 13:00, 16:00 y 23:00.'},
            status=400,
        )

    ids_validos = {franja.id for franja in franjas}
    cantidades = {}
    for item in distribucion:
        if not isinstance(item, dict):
            return JsonResponse({'error': 'La distribución contiene datos inválidos.'}, status=400)
        franja_id = item.get('franja_id')
        cantidad = item.get('cantidad')
        if (not isinstance(franja_id, int) or isinstance(franja_id, bool)
                or not isinstance(cantidad, int) or isinstance(cantidad, bool)
                or cantidad < 0 or cantidad > 32767
                or franja_id not in ids_validos or franja_id in cantidades):
            return JsonResponse(
                {'error': 'Cada franja debe tener un cupo válido y único.'},
                status=400,
            )
        cantidades[franja_id] = cantidad

    if set(cantidades) != ids_validos:
        return JsonResponse(
            {'error': 'Debes indicar un cupo para cada una de las cuatro franjas.'},
            status=400,
        )
    if sum(cantidades.values()) != len(tecnicos):
        return JsonResponse(
            {
                'error': (
                    f'Los cupos deben sumar {len(tecnicos)}, que es el total de '
                    'técnicos activos sin franja.'
                ),
                'total_tecnicos': len(tecnicos),
                'suma_cupos': sum(cantidades.values()),
            },
            status=400,
        )
    franja_noche = next(
        franja for franja in franjas
        if franja.hora_inicio.strftime('%H:%M') == '16:00'
    )
    minimo_noche = max(
        0,
        2 - Empleado.objects.filter(activo=True, franja=franja_noche).count(),
    )
    if cantidades[franja_noche.id] < minimo_noche:
        return JsonResponse(
            {
                'error': (
                    f'Noche (16:00–23:00) necesita al menos '
                    f'{minimo_noche} técnico(s) adicional(es) sin franja para '
                    'mantener cobertura durante los descansos 6x1.'
                )
            },
            status=400,
        )

    with transaction.atomic():
        AsignacionSemanal.objects.filter(lunes=lunes).delete()
        AsignacionSemanal.objects.bulk_create([
            AsignacionSemanal(
                lunes=lunes,
                franja_id=franja_id,
                cantidad=cantidad,
            )
            for franja_id, cantidad in cantidades.items()
        ])

    return JsonResponse({
        'ok': True,
        'lunes': lunes.isoformat(),
        'total_tecnicos': len(tecnicos),
        'suma_cupos': sum(cantidades.values()),
    })


@require_POST
@solo_staff
def api_limpiar_semana(request):
    fecha = _fecha_estricta(request.POST.get('fecha'))
    if fecha is None:
        return JsonResponse(
            {'error': 'Fecha inválida. Usa el formato AAAA-MM-DD.'}, status=400
        )

    lunes = lunes_de(fecha)
    domingo = lunes + timedelta(days=6)
    limpiados = Turno.objects.filter(
        fecha__range=(lunes, domingo)
    ).update(
        descanso=False,
        inicio=None,
        fin=None,
        manual=False,
        novedad='',
    )
    return JsonResponse({'ok': True, 'limpiados': limpiados})


def _fecha_estricta(texto):
    """'2026-10-21' -> fecha. Sin valor o con formato inválido devuelve None."""
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def _buscar_empleado(valor):
    try:
        return Empleado.objects.select_related('rol').filter(pk=int(valor), activo=True).first()
    except (TypeError, ValueError):
        return None


def _respuesta_cambio(operacion):
    """Ejecuta un cambio de turnos y traduce las excepciones a respuestas JSON."""
    try:
        operacion()
    except CoberturaInsuficiente as error:
        return JsonResponse({'error': str(error), 'problemas': error.problemas}, status=409)
    except CambioInvalido as error:
        return JsonResponse({'error': str(error)}, status=400)
    return JsonResponse({'ok': True})


@require_POST
@solo_staff
def api_turno_descanso(request):
    datos = _leer_json(request) or {}
    empleado = _buscar_empleado(datos.get('empleado_id'))
    fecha = _fecha_estricta(datos.get('fecha'))
    if empleado is None or fecha is None:
        return JsonResponse({'error': 'Faltan datos: empleado o fecha.'}, status=400)
    return _respuesta_cambio(
        lambda: cambiar_descansos([(empleado, fecha)], forzar=bool(datos.get('forzar')))
    )


@require_POST
@solo_staff
def api_turno_intercambiar(request):
    datos = _leer_json(request) or {}
    a = _buscar_empleado(datos.get('empleado_id'))
    b = _buscar_empleado(datos.get('companero_id'))
    fecha = _fecha_estricta(datos.get('fecha'))
    if a is None or b is None or fecha is None:
        return JsonResponse({'error': 'Faltan datos: empleados o fecha.'}, status=400)
    return _respuesta_cambio(
        lambda: intercambiar_descansos(a, b, fecha, forzar=bool(datos.get('forzar')))
    )


@require_POST
@solo_staff
def api_turno_horario(request):
    datos = _leer_json(request) or {}
    empleado = _buscar_empleado(datos.get('empleado_id'))
    fecha = _fecha_estricta(datos.get('fecha'))
    inicio_texto = datos.get('inicio')
    if empleado is None or fecha is None or not isinstance(inicio_texto, str):
        return JsonResponse({'error': 'Faltan datos: empleado, fecha u hora de inicio.'}, status=400)
    try:
        inicio = datetime.strptime(inicio_texto, '%H:%M').time()
    except ValueError:
        return JsonResponse(
            {'error': 'La hora de inicio no es válida. Usa el formato HH:MM.'},
            status=400,
        )
    return _respuesta_cambio(
        lambda: cambiar_horario(empleado, fecha, inicio)
    )


@require_POST
@solo_staff
def api_novedad_guardar(request):
    datos = _leer_json(request)
    if datos is None:
        return JsonResponse({'error': 'Los datos enviados no son válidos.'}, status=400)

    pk = datos.get('id')
    if pk:
        novedad = Novedad.objects.filter(pk=pk).first()
        if novedad is None:
            return JsonResponse({'error': 'Esa novedad ya no existe.'}, status=404)
        inicio_viejo, fin_viejo = novedad.fecha_inicio, novedad.fecha_fin
    else:
        novedad = Novedad()
        inicio_viejo = fin_viejo = None

    for campo in ['empleado_id', 'tipo', 'fecha_inicio', 'fecha_fin', 'nota']:
        if campo in datos:
            valor = datos[campo]
            if isinstance(valor, str):
                valor = valor.strip()
            setattr(novedad, campo, valor)

    try:
        novedad.full_clean()
    except ValidationError as error:
        return JsonResponse({'error': ' '.join(error.messages)}, status=400)
    novedad.save()

    # Recalcular lo que ya estaba generado, tanto con las fechas nuevas como con las viejas
    inicio = min(d for d in (novedad.fecha_inicio, inicio_viejo) if d)
    fin = max(d for d in (novedad.fecha_fin, fin_viejo) if d)
    avisos, semanas = regenerar_rango(inicio, fin)
    return JsonResponse({'ok': True, 'avisos': avisos, 'semanas': semanas})


@require_POST
@solo_staff
def api_novedad_eliminar(request):
    datos = _leer_json(request)
    if datos is None or not datos.get('id'):
        return JsonResponse({'error': 'Falta indicar qué novedad eliminar.'}, status=400)

    novedad = Novedad.objects.filter(pk=datos['id']).first()
    if novedad is None:
        return JsonResponse({'error': 'Esa novedad ya no existe.'}, status=404)

    inicio, fin = novedad.fecha_inicio, novedad.fecha_fin
    novedad.delete()
    avisos, semanas = regenerar_rango(inicio, fin)
    return JsonResponse({'ok': True, 'avisos': avisos, 'semanas': semanas})