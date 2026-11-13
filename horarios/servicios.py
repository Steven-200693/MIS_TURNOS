from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q

from .models import AsignacionSemanal, Franja, Empleado, Novedad, Turno

# Días de la semana: 0 = lunes ... 6 = domingo
DIAS_PERMITIDOS = {
    'CUALQUIERA': [0, 1, 2, 3, 4, 5, 6],
    'SEMANA': [0, 1, 2, 3, 4],
    'FINDE': [5, 6],
}
NOMBRES_DIA = ['lunes', 'martes', 'miércoles', 'jueves',
               'viernes', 'sábado', 'domingo']

# Festivos nacionales colombianos trasladados al lunes cuando aplica la Ley 51.
FESTIVOS_COLOMBIA_2026 = {
    date(2026, 1, 1): 'Año Nuevo',
    date(2026, 1, 12): 'Día de los Reyes Magos',
    date(2026, 3, 23): 'Día de San José',
    date(2026, 4, 2): 'Jueves Santo',
    date(2026, 4, 3): 'Viernes Santo',
    date(2026, 5, 1): 'Día del Trabajo',
    date(2026, 5, 18): 'Ascensión del Señor',
    date(2026, 6, 8): 'Corpus Christi',
    date(2026, 6, 15): 'Sagrado Corazón de Jesús',
    date(2026, 6, 29): 'San Pedro y San Pablo',
    date(2026, 7, 20): 'Día de la Independencia',
    date(2026, 8, 7): 'Batalla de Boyacá',
    date(2026, 8, 17): 'Asunción de la Virgen',
    date(2026, 10, 12): 'Día de la Raza',
    date(2026, 11, 2): 'Día de Todos los Santos',
    date(2026, 11, 16): 'Independencia de Cartagena',
    date(2026, 12, 8): 'Inmaculada Concepción',
    date(2026, 12, 25): 'Navidad',
}


def festivos_colombia(anio):
    if anio == 2026:
        return FESTIVOS_COLOMBIA_2026

    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    pascua = date(anio, mes, dia)

    festivos = {
        date(anio, 1, 1): 'Año Nuevo',
        date(anio, 5, 1): 'Día del Trabajo',
        date(anio, 7, 20): 'Día de la Independencia',
        date(anio, 8, 7): 'Batalla de Boyacá',
        date(anio, 12, 8): 'Inmaculada Concepción',
        date(anio, 12, 25): 'Navidad',
        pascua - timedelta(days=3): 'Jueves Santo',
        pascua - timedelta(days=2): 'Viernes Santo',
    }

    festivos_emiliani = (
        (1, 6, 'Día de los Reyes Magos'),
        (3, 19, 'Día de San José'),
        (6, 29, 'San Pedro y San Pablo'),
        (8, 15, 'Asunción de la Virgen'),
        (10, 12, 'Día de la Raza'),
        (11, 1, 'Día de Todos los Santos'),
        (11, 11, 'Independencia de Cartagena'),
    )
    for mes_festivo, dia_festivo, nombre in festivos_emiliani:
        fecha = date(anio, mes_festivo, dia_festivo)
        fecha += timedelta(days=(7 - fecha.weekday()) % 7)
        festivos[fecha] = nombre

    for dias_despues, nombre in (
        (39, 'Ascensión del Señor'),
        (60, 'Corpus Christi'),
        (68, 'Sagrado Corazón de Jesús'),
    ):
        fecha = pascua + timedelta(days=dias_despues)
        fecha += timedelta(days=(7 - fecha.weekday()) % 7)
        festivos[fecha] = nombre

    return festivos


def fecha_fin_vacaciones(fecha_inicio):
    fecha = fecha_inicio
    dias_contados = 0
    festivos = {}
    while dias_contados < 15:
        if fecha.year not in festivos:
            festivos.update(festivos_colombia(fecha.year))
        if fecha.weekday() != 6 and fecha not in festivos:
            dias_contados += 1
        if dias_contados == 15:
            return fecha
        fecha += timedelta(days=1)


class CambioInvalido(Exception):
    """El cambio pedido rompe una regla. El mensaje se muestra tal cual al usuario."""


class CoberturaInsuficiente(CambioInvalido):
    """El cambio deja una franja con menos gente de la necesaria."""
    def __init__(self, problemas):
        super().__init__('El cambio deja franjas sin cobertura suficiente.')
        self.problemas = problemas


def lunes_de(fecha):
    """Devuelve el lunes de la semana a la que pertenece la fecha."""
    return fecha - timedelta(days=fecha.weekday())


def _dias_de_semana(fecha):
    lunes = lunes_de(fecha)
    return [lunes + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------
# Apoyo del generador
# ---------------------------------------------------------------

def _novedades_de_semana(dias):
    """Devuelve {empleado_id: {indice_del_dia: tipo}} para la semana dada."""
    resultado = defaultdict(dict)
    consulta = Novedad.objects.filter(fecha_inicio__lte=dias[6], fecha_fin__gte=dias[0])
    for n in consulta:
        for i, d in enumerate(dias):
            if n.fecha_inicio <= d <= n.fecha_fin:
                resultado[n.empleado_id][i] = n.tipo
    return resultado


def _datos_turno(franja, fecha_dia, estado):
    """estado: 'trabajo', 'descanso' o el código de una novedad."""
    datos = {'franja': franja, 'remoto': False, 'manual': False, 'novedad': '',
             'descanso': False, 'inicio': None, 'fin': None}
    if estado == 'descanso':
        datos['descanso'] = True
    elif estado == 'trabajo':
        entrada = datetime.combine(fecha_dia, franja.hora_inicio)
        salida = entrada + timedelta(hours=franja.rol.horas_por_dia)
        datos['inicio'], datos['fin'] = entrada.time(), salida.time()
    else:
        datos['novedad'] = estado
    return datos


def _turno_fin_semana_manual_valido(turno, dia):
    if turno is None or turno.novedad:
        return False
    if turno.descanso:
        return (
            turno.inicio is None
            and turno.fin is None
            and not turno.remoto
        )
    return (
        turno.inicio == time(6)
        and turno.fin == time(18)
        and turno.remoto == (dia == 6)
    )


def _turno_fin_semana_intercambiable(turno, dia):
    if turno.novedad:
        return False
    if turno.descanso:
        return (
            turno.inicio is None
            and turno.fin is None
            and not turno.remoto
        )
    return (
        turno.inicio is not None
        and turno.fin is not None
        and turno.remoto == (dia == 6)
    )


def _dias_especiales_previos(empleados, fecha):
    """Cuenta los fines de semana/festivos trabajados antes de una fecha."""
    conteos = defaultdict(int)
    if not empleados:
        return conteos
    turnos = Turno.objects.filter(
        empleado__activo=True,
        empleado__rol_id=empleados[0].rol_id,
        fecha__lt=fecha,
        descanso=False,
        novedad='',
        inicio__isnull=False,
    ).only('empleado_id', 'fecha')
    for turno in turnos:
        if turno.fecha.weekday() >= 5 or turno.fecha in FESTIVOS_COLOMBIA_2026:
            conteos[turno.empleado_id] += 1
    return conteos


def _festivos_trabajados_previos(empleados, fecha):
    conteos = defaultdict(int)
    if not empleados:
        return conteos
    fechas_festivas = [
        festivo for festivo in FESTIVOS_COLOMBIA_2026
        if festivo < fecha
    ]
    turnos = Turno.objects.filter(
        empleado_id__in=[empleado.id for empleado in empleados],
        fecha__in=fechas_festivas,
        descanso=False,
        novedad='',
        inicio__isnull=False,
    ).values_list('empleado_id', flat=True)
    for empleado_id in turnos:
        conteos[empleado_id] += 1
    return conteos


def _es_supervisor(empleado):
    return empleado.rol.nombre.strip().casefold() == 'supervisor'


def _asignar_guardia_festiva_supervisores(fecha, preferido=None, excluir=()):
    supervisores = list(
        Empleado.objects.filter(
            activo=True,
            rol__nombre__iexact='Supervisor',
        ).select_related('rol', 'franja').order_by('id')
    )
    turnos = {
        turno.empleado_id: turno
        for turno in Turno.objects.filter(
            empleado__in=supervisores,
            fecha=fecha,
        ).select_related('franja')
    }
    excluidos = set(excluir)
    elegibles = [
        empleado for empleado in supervisores
        if (not empleado.fecha_ingreso or empleado.fecha_ingreso <= fecha)
        and empleado.id not in excluidos
        and empleado.id in turnos
        and not turnos[empleado.id].novedad
    ]
    if preferido is not None:
        elegibles = [
            empleado for empleado in elegibles
            if empleado.id == preferido.id
        ]
    if not elegibles:
        raise CambioInvalido(
            f"No hay supervisores disponibles para cubrir el festivo "
            f"{fecha.isoformat()}."
        )

    conteos = _festivos_trabajados_previos(supervisores, fecha)
    elegibles.sort(key=lambda empleado: (
        conteos[empleado.id],
        (empleado.id - fecha.toordinal()) % len(supervisores),
        empleado.id,
    ))
    seleccionado = elegibles[0]
    for empleado in supervisores:
        turno = turnos.get(empleado.id)
        if turno is None or turno.novedad:
            continue
        if empleado.id == seleccionado.id:
            franja = turno.franja or empleado.franja or Franja.objects.filter(
                rol__nombre__iexact='Supervisor'
            ).order_by('hora_inicio', 'id').first()
            if franja is None:
                raise CambioInvalido(
                    'No hay una franja configurada para los supervisores.'
                )
            turno.franja = franja
            turno.descanso = False
            turno.inicio = time(6)
            turno.fin = time(18)
            turno.remoto = True
        else:
            turno.descanso = True
            turno.inicio = None
            turno.fin = None
            turno.remoto = False
        turno.manual = True
        turno.save(update_fields=[
            'franja', 'descanso', 'inicio', 'fin', 'remoto', 'manual',
        ])


def _asignar_guardia_festiva(
    franja, empleados, fecha, bloqueos, avisos, supervisor=False,
    descartar_manuales=False, festivo_cuenta_como_descanso=False,
):
    """Deja un solo trabajador por franja en festivo y reparte la carga."""
    indice = fecha.weekday()
    for empleado in empleados:
        novedad = bloqueos.get(empleado.id, {}).get(indice)
        if novedad and (
            empleado.fecha_ingreso is None
            or fecha >= empleado.fecha_ingreso
        ):
            Turno.objects.update_or_create(
                empleado=empleado,
                fecha=fecha,
                defaults=_datos_turno(franja, fecha, novedad),
            )
    elegibles = [
        empleado for empleado in empleados
        if (not empleado.fecha_ingreso or empleado.fecha_ingreso <= fecha)
        and indice not in bloqueos.get(empleado.id, {})
    ]
    existentes = {
        turno.empleado_id: turno
        for turno in Turno.objects.filter(
            empleado__in=empleados, fecha=fecha
        ).select_related('franja')
    }
    manuales = {
        empleado.id: existentes.get(empleado.id)
        for empleado in empleados
        if existentes.get(empleado.id)
        and existentes[empleado.id].manual
        and not descartar_manuales
    }
    manuales_trabajando = [
        empleado for empleado in elegibles
        if empleado.id in manuales
        and not manuales[empleado.id].descanso
        and manuales[empleado.id].inicio
    ]
    fijados_descanso = {
        empleado.id for empleado in elegibles
        if empleado.id in manuales and manuales[empleado.id].descanso
    }
    disponibles = [
        empleado for empleado in elegibles
        if empleado.id not in fijados_descanso
    ]
    if not disponibles:
        avisos.append(
            f"{franja.rol.nombre} · {franja.nombre}: no hay personal disponible "
            f"para cubrir el festivo {fecha.isoformat()}."
        )
        return

    conteos = (
        _festivos_trabajados_previos(empleados, fecha)
        if supervisor
        else _dias_especiales_previos(empleados, fecha)
    )
    candidatos = manuales_trabajando or disponibles
    candidatos.sort(key=lambda empleado: (
        conteos[empleado.id],
        (empleado.id - fecha.toordinal() - franja.id) % max(len(empleados), 1),
        empleado.id,
    ))
    seleccionado = candidatos[0]
    entrada = time(6) if supervisor else franja.hora_inicio
    salida = (
        (datetime.combine(fecha, entrada) + timedelta(hours=12)).time()
        if supervisor
        else (
            datetime.combine(fecha, entrada)
            + timedelta(hours=franja.rol.horas_por_dia)
        ).time()
    )

    for empleado in empleados:
        if empleado.fecha_ingreso and fecha < empleado.fecha_ingreso:
            continue
        if empleado.id in bloqueos.get(empleado.id, {}):
            continue
        existente = existentes.get(empleado.id)
        franja_empleado = (
            existente.franja if existente and existente.franja_id
            else empleado.franja or franja
        )
        if empleado.id == seleccionado.id:
            datos = _datos_turno(franja_empleado, fecha, 'trabajo')
            datos.update(
                inicio=entrada,
                fin=salida,
                remoto=supervisor,
                manual=bool(
                    empleado.id in manuales_trabajando
                    and manuales[empleado.id].manual
                ),
            )
        else:
            datos = _datos_turno(franja_empleado, fecha, 'descanso')
        Turno.objects.update_or_create(
            empleado=empleado, fecha=fecha, defaults=datos
        )
        if (
            festivo_cuenta_como_descanso
            and empleado.id != seleccionado.id
        ):
            descanso_semanal = Turno.objects.filter(
                empleado=empleado,
                fecha__range=(lunes_de(fecha), lunes_de(fecha) + timedelta(days=6)),
                descanso=True,
                manual=False,
                novedad='',
            ).exclude(
                fecha__in=[
                    festivo for festivo in FESTIVOS_COLOMBIA_2026
                    if lunes_de(fecha) <= festivo <= lunes_de(fecha) + timedelta(days=6)
                ]
            ).order_by('fecha').first()
            if descanso_semanal:
                franja_descanso = (
                    descanso_semanal.franja or empleado.franja or franja
                )
                descanso_semanal.descanso = False
                descanso_semanal.inicio = franja_descanso.hora_inicio
                descanso_semanal.fin = (
                    datetime.combine(descanso_semanal.fecha, franja_descanso.hora_inicio)
                    + timedelta(hours=franja_descanso.rol.horas_por_dia)
                ).time()
                descanso_semanal.save(
                    update_fields=['descanso', 'inicio', 'fin']
                )

    if festivo_cuenta_como_descanso:
        inicio_semana = lunes_de(fecha)
        fin_semana = inicio_semana + timedelta(days=6)
        festivos_semana = [
            festivo for festivo in FESTIVOS_COLOMBIA_2026
            if inicio_semana <= festivo <= fin_semana
        ]
        descanso_regular = Turno.objects.filter(
            empleado=seleccionado,
            fecha__range=(inicio_semana, fin_semana),
            descanso=True,
            novedad='',
        ).exclude(fecha__in=festivos_semana).exists()
        if not descanso_regular:
            alternativas = list(
                Turno.objects.filter(
                    empleado=seleccionado,
                    fecha__range=(inicio_semana, fin_semana),
                    descanso=False,
                    novedad='',
                    manual=False,
                    inicio__isnull=False,
                ).exclude(fecha__in=festivos_semana).order_by('fecha')
            )
            cobertura = []
            for alternativa in alternativas:
                personas_trabajando = Turno.objects.filter(
                    franja_id=alternativa.franja_id,
                    fecha=alternativa.fecha,
                    descanso=False,
                    novedad='',
                    inicio__isnull=False,
                    empleado__activo=True,
                ).count()
                cobertura.append((personas_trabajando, alternativa))
            con_cobertura = [
                (personas, alternativa)
                for personas, alternativa in cobertura
                if personas > alternativa.franja.minimo_personas
            ]
            opciones = con_cobertura or cobertura
            if opciones:
                _, descanso_regular = max(
                    opciones,
                    key=lambda item: (
                        item[0] - item[1].franja.minimo_personas,
                        -item[1].fecha.toordinal(),
                    ),
                )
                if not con_cobertura:
                    avisos.append(
                        f"{seleccionado.nombre}: el descanso compensatorio por "
                        f"el festivo {fecha.isoformat()} reduce la cobertura de "
                        f"{descanso_regular.franja.nombre} el "
                        f"{descanso_regular.fecha.isoformat()}."
                    )
                descanso_regular.descanso = True
                descanso_regular.inicio = None
                descanso_regular.fin = None
                descanso_regular.save(
                    update_fields=['descanso', 'inicio', 'fin']
                )


def _asignaciones_fin_de_semana(lunes):
    """Distribuye dos descansos y turnos de sábado presencial/domingo remoto."""
    supervisores = list(
        Empleado.objects.filter(
            activo=True, rol__nombre__iexact='Supervisor'
        ).order_by('id')
    )
    if len(supervisores) != 4:
        return {}, len(supervisores)

    rotacion = ((0, 1), (2, 3), (1, 2), (3, 0))
    semana_ancla = date(2000, 1, 3)
    numero_semana = (lunes - semana_ancla).days // 7
    indices_remotos = rotacion[numero_semana % len(rotacion)]

    # El valor indica el día trabajado; None significa descanso ambos días.
    return {
        supervisor.id: (
            5 + indices_remotos.index(indice) if indice in indices_remotos else None
        )
        for indice, supervisor in enumerate(supervisores)
    }, 4


def distribucion_tecnicos_semana(lunes):
    """Devuelve franjas, técnicos sin franja, cupos y estado de la configuración."""
    franjas = list(
        Franja.objects.filter(
            Q(rol__nombre__iexact='Tecnico') | Q(rol__nombre__iexact='Técnico'),
            hora_inicio__in=(time(6), time(13), time(16), time(23)),
        ).select_related('rol').order_by('hora_inicio')
    )
    empleados = list(
        Empleado.objects.filter(
            Q(rol__nombre__iexact='Tecnico') | Q(rol__nombre__iexact='Técnico'),
            activo=True,
            franja__isnull=True,
        ).order_by('id')
    )
    horas_requeridas = {time(6), time(13), time(16), time(23)}
    if len(franjas) != len(horas_requeridas) or {
        franja.hora_inicio for franja in franjas
    } != horas_requeridas:
        return franjas, empleados, {}, False, True

    franja_noche = next(franja for franja in franjas if franja.hora_inicio == time(16))
    tecnicos_noche_fijos = Empleado.objects.filter(
        activo=True, franja=franja_noche
    ).count()
    cupo_noche_minimo = max(0, 1 - tecnicos_noche_fijos)

    semana_ancla = date(2000, 1, 3)
    numero_semana = (lunes - semana_ancla).days // 7
    guardados = dict(AsignacionSemanal.objects.filter(lunes=lunes).values_list(
        'franja_id', 'cantidad'
    ))
    if guardados and set(guardados) == {franja.id for franja in franjas}:
        if (
            sum(guardados.values()) == len(empleados)
            and guardados[franja_noche.id] >= cupo_noche_minimo
        ):
            return franjas, empleados, guardados, True, False
        return franjas, empleados, {}, False, True
    if guardados:
        return franjas, empleados, {}, False, True

    conteos = {
        franja.id: Empleado.objects.filter(activo=True, franja=franja).count()
        for franja in franjas
    }
    asignaciones = {franja.id: 0 for franja in franjas}
    if cupo_noche_minimo > len(empleados):
        return franjas, empleados, {}, False, True
    asignaciones[franja_noche.id] = cupo_noche_minimo
    conteos[franja_noche.id] += cupo_noche_minimo
    orden_franjas = franjas[numero_semana % len(franjas):] + franjas[
        :numero_semana % len(franjas)
    ]
    for _ in range(len(empleados) - cupo_noche_minimo):
        franja = min(orden_franjas, key=lambda item: conteos[item.id])
        asignaciones[franja.id] += 1
        conteos[franja.id] += 1
    return franjas, empleados, asignaciones, False, False


def _asignaciones_tecnicos_sin_franja(lunes):
    """Asigna el cupo semanal definido a cada franja y rota el personal."""
    franjas, empleados, cupos, configurada, configuracion_invalida = (
        distribucion_tecnicos_semana(lunes)
    )
    if configuracion_invalida or not empleados:
        return {}, set(), configuracion_invalida

    semana_ancla = date(2000, 1, 3)
    numero_semana = (lunes - semana_ancla).days // 7
    asignaciones = {franja.id: set() for franja in franjas}
    cupos_por_franja = [
        franja.id
        for franja in franjas
        for _ in range(cupos[franja.id])
    ]
    desplazamiento = numero_semana % len(cupos_por_franja)
    cupos_rotados = (
        cupos_por_franja[desplazamiento:] + cupos_por_franja[:desplazamiento]
    )
    for empleado, franja_id in zip(empleados, cupos_rotados):
        asignaciones[franja_id].add(empleado.id)

    return asignaciones, {empleado.rol_id for empleado in empleados}, False


# ---------------------------------------------------------------
# Generador automático
# ---------------------------------------------------------------

@transaction.atomic
def generar_semana(fecha, descartar_manuales=False):
    """Genera los turnos de la semana de `fecha`. Devuelve una lista de avisos.

    Respeta los descansos ajustados a mano (salvo descartar_manuales=True)
    y las novedades registradas (incapacidades, compensatorios, etc.).
    """
    dias = _dias_de_semana(fecha)
    lunes = dias[0]
    avisos = []
    descansos_por_rol = {}
    bloqueos = _novedades_de_semana(dias)
    asignaciones_fin_de_semana, total_supervisores = _asignaciones_fin_de_semana(lunes)
    asignaciones_tecnicos, roles_tecnicos_sin_franja, franjas_tecnicas_faltantes = (
        _asignaciones_tecnicos_sin_franja(lunes)
    )
    politica_supervisores = len(asignaciones_fin_de_semana) == 4
    if not politica_supervisores and total_supervisores:
        avisos.append(
            'La rotación de fin de semana requiere exactamente cuatro supervisores '
            'activos; se conservaron sus turnos habituales.'
        )
    if franjas_tecnicas_faltantes:
        avisos.append(
            'No se aplicó la distribución de técnicos sin franja: verifica que '
            'existan las cuatro franjas, que los cupos sumen el total actual y '
            'que Noche y Madrugada tengan personal suficiente para alternar '
            'descansos 6x1.'
        )

    if descartar_manuales:
        Turno.objects.filter(fecha__in=dias, manual=True).update(manual=False)
        Turno.objects.filter(
            fecha__in=dias,
            trabajar_sin_descanso_semanal=True,
        ).update(trabajar_sin_descanso_semanal=False)

    # Descansos fijados a mano: empleado_id -> índice del día (0 = lunes)
    fijos = {
        t.empleado_id: (t.fecha - lunes).days
        for t in Turno.objects.filter(fecha__in=dias, manual=True, descanso=True)
    }
    turnos_manuales = {
        (t.empleado_id, (t.fecha - lunes).days): t
        for t in Turno.objects.filter(fecha__in=dias, manual=True)
    }
    trabajar_sin_descanso = set(
        Turno.objects.filter(
            fecha__in=dias,
            trabajar_sin_descanso_semanal=True,
        ).values_list('empleado_id', flat=True)
    )

    for franja in Franja.objects.select_related('rol'):
        etiqueta = f"{franja.rol.nombre} · {franja.nombre}"
        if franja.rol_id in roles_tecnicos_sin_franja:
            seleccion_empleados = Q(franja=franja) | Q(
                pk__in=asignaciones_tecnicos.get(franja.id, set())
            )
        else:
            seleccion_empleados = Q(franja=franja) | Q(
                franja__isnull=True,
                turno__franja=franja,
                turno__fecha__in=dias,
            )
        empleados = list(
            Empleado.objects.filter(activo=True)
            .filter(seleccion_empleados)
            .distinct()
            .order_by('id')
        )

        if not empleados:
            if franja.minimo_personas > 0:
                avisos.append(f"{etiqueta}: no tiene empleados asignados.")
            continue

        conteo_rol = descansos_por_rol.setdefault(
            franja.rol_id, {d: 0 for d in range(7)}
        )
        conteo_franja = {d: 0 for d in range(7)}

        # 0) Las novedades cuentan como ausencias
        for emp in empleados:
            for d in bloqueos.get(emp.id, {}):
                conteo_franja[d] += 1

        # 1) Separar descansos fijados a mano de los que se reparten
        libres, con_fijo = [], []
        for emp in empleados:
            dia_fijo = fijos.get(emp.id)
            if dia_fijo is not None and dia_fijo not in bloqueos.get(emp.id, {}):
                con_fijo.append(emp)
                conteo_franja[dia_fijo] += 1
                conteo_rol[dia_fijo] += 1
            else:
                libres.append(emp)

        # 2) Repartir el descanso semanal de los demás
        libres.sort(key=lambda e: len(DIAS_PERMITIDOS[e.preferencia_descanso]))

        for emp in libres:
            bloq = bloqueos.get(emp.id, {})
            primer_dia = (
                max(0, (emp.fecha_ingreso - lunes).days)
                if emp.fecha_ingreso else 0
            )
            preferidos = DIAS_PERMITIDOS[emp.preferencia_descanso]
            manuales_emp = {
                dia for (empleado_id, dia) in turnos_manuales
                if empleado_id == emp.id and dia >= primer_dia and dia not in bloq
            }
            candidatos = [] if emp.id in trabajar_sin_descanso else [
                d for d in preferidos
                if d >= primer_dia and d not in bloq and d not in manuales_emp
            ]
            if not candidatos and emp.id not in trabajar_sin_descanso:
                candidatos = [
                    d for d in range(primer_dia, 7)
                    if d not in bloq and d not in manuales_emp
                ]

            dia_auto = None
            if candidatos:
                dia_auto = min(
                    candidatos,
                    key=lambda d: (conteo_franja[d], conteo_rol[d], d),
                )
                conteo_franja[dia_auto] += 1
                conteo_rol[dia_auto] += 1

            for i in range(7):
                if emp.fecha_ingreso and dias[i] < emp.fecha_ingreso:
                    continue
                if i in bloq:
                    estado = bloq[i]
                elif i == dia_auto:
                    estado = 'descanso'
                else:
                    if (emp.id, i) in turnos_manuales:
                        continue
                    estado = 'trabajo'
                Turno.objects.update_or_create(
                    empleado=emp, fecha=dias[i],
                    defaults=_datos_turno(franja, dias[i], estado),
                )

        # 3) Quienes tienen descanso fijo: solo se actualizan sus novedades
        for emp in con_fijo:
            bloq = bloqueos.get(emp.id, {})
            existentes = {t.fecha: t for t in
                          Turno.objects.filter(empleado=emp, fecha__in=dias)}
            for i in range(7):
                if emp.fecha_ingreso and dias[i] < emp.fecha_ingreso:
                    continue
                if i == fijos[emp.id]:
                    continue
                deseado = bloq.get(i, '')
                actual = existentes.get(dias[i])
                if actual and actual.manual and i not in bloq:
                    continue
                if actual is None or actual.novedad != deseado:
                    Turno.objects.update_or_create(
                        empleado=emp, fecha=dias[i],
                        defaults=_datos_turno(franja, dias[i], deseado or 'trabajo'),
                    )

        if (
            franja.rol.nombre.casefold() in ('tecnico', 'técnico')
            and franja.hora_inicio == time(16)
            and len(empleados) >= 2
        ):
            semana_ancla = date(2000, 1, 3)
            numero_semana = (lunes - semana_ancla).days // 7
            equipo = empleados[numero_semana % len(empleados):] + empleados[
                :numero_semana % len(empleados)
            ]
            descansos_ocupados = {
                fijos[emp.id]
                for emp in equipo
                if (
                    emp.id in fijos
                    and dias[fijos[emp.id]] >= emp.fecha_ingreso
                    and fijos[emp.id] not in bloqueos.get(emp.id, {})
                )
            }
            dias_rotacion = [6, 5, 4, 3, 2, 1, 0]
            for emp in equipo:
                if emp.id in fijos:
                    continue
                bloq = bloqueos.get(emp.id, {})
                disponibles = [
                    dia for dia in dias_rotacion
                    if dia not in descansos_ocupados
                    and (
                        emp.fecha_ingreso is None
                        or dias[dia] >= emp.fecha_ingreso
                    )
                    and dia not in bloq
                    and (emp.id, dia) not in turnos_manuales
                ]
                if not disponibles:
                    continue

                dia_descanso = disponibles[0]
                descanso_actual = Turno.objects.filter(
                    empleado=emp,
                    fecha__in=dias,
                    descanso=True,
                    manual=False,
                ).first()
                if descanso_actual and descanso_actual.fecha != dias[dia_descanso]:
                    descanso_actual.descanso = False
                    descanso_actual.inicio = franja.hora_inicio
                    descanso_actual.fin = (
                        datetime.combine(descanso_actual.fecha, franja.hora_inicio)
                        + timedelta(hours=franja.rol.horas_por_dia)
                    ).time()
                    descanso_actual.save(
                        update_fields=['descanso', 'inicio', 'fin']
                    )
                Turno.objects.update_or_create(
                    empleado=emp,
                    fecha=dias[dia_descanso],
                    defaults=_datos_turno(franja, dias[dia_descanso], 'descanso'),
                )
                descansos_ocupados.add(dia_descanso)

        if politica_supervisores and franja.rol.nombre.casefold() == 'supervisor':
            for emp in empleados:
                if emp.id not in asignaciones_fin_de_semana:
                    continue
                dia_cobertura = asignaciones_fin_de_semana[emp.id]
                for dia in (5, 6):
                    if emp.fecha_ingreso and dias[dia] < emp.fecha_ingreso:
                        continue
                    novedad = bloqueos.get(emp.id, {}).get(dia)
                    if novedad:
                        continue
                    existente = Turno.objects.filter(
                        empleado=emp, fecha=dias[dia]
                    ).first()
                    if (
                        existente
                        and existente.manual
                        and not descartar_manuales
                        and _turno_fin_semana_manual_valido(existente, dia)
                    ):
                        avisos.append(
                            f"{emp.nombre}: se respetó el ajuste manual del "
                            f"{NOMBRES_DIA[dia]}."
                        )
                        continue

                    if dia == dia_cobertura:
                        datos = _datos_turno(franja, dias[dia], 'trabajo')
                        datos.update(
                            inicio=datetime.strptime('06:00', '%H:%M').time(),
                            fin=datetime.strptime('18:00', '%H:%M').time(),
                            remoto=(dia == 6),
                        )
                    else:
                        datos = _datos_turno(franja, dias[dia], 'descanso')
                    Turno.objects.update_or_create(
                        empleado=emp, fecha=dias[dia], defaults=datos
                    )

        if franja.rol.nombre.casefold() in ('tecnico', 'técnico'):
            for fecha_dia in dias:
                if fecha_dia in FESTIVOS_COLOMBIA_2026:
                    _asignar_guardia_festiva(
                        franja,
                        empleados,
                        fecha_dia,
                        bloqueos,
                        avisos,
                        descartar_manuales=descartar_manuales,
                        festivo_cuenta_como_descanso=True,
                    )
        # 4) Revisar la cobertura de la franja, día por día
        for d in range(7):
            if (
                franja.rol.nombre.casefold() == 'supervisor'
                and dias[d] in FESTIVOS_COLOMBIA_2026
            ):
                continue
            trabajan = Turno.objects.filter(
                empleado__activo=True,
                franja=franja,
                fecha=dias[d],
                descanso=False,
                novedad='',
                inicio__isnull=False,
                fin__isnull=False,
            ).count()
            if trabajan < franja.minimo_personas:
                texto = (f"{etiqueta}: el {NOMBRES_DIA[d]} hay {trabajan} "
                         f"y se necesitan {franja.minimo_personas}.")
                ausentes = [e.nombre for e in empleados if d in bloqueos.get(e.id, {})]
                if ausentes:
                    texto += f" Ausentes por novedad: {', '.join(ausentes)}."
                avisos.append(texto)

    supervisores = list(
        Empleado.objects.filter(
            activo=True, rol__nombre__iexact='Supervisor'
        ).select_related('rol', 'franja').order_by('id')
    )
    if supervisores:
        franja_supervisor = Franja.objects.filter(
            rol__nombre__iexact='Supervisor'
        ).order_by('hora_inicio', 'id').first()
        if franja_supervisor:
            for fecha_dia in dias:
                if fecha_dia in FESTIVOS_COLOMBIA_2026:
                    _asignar_guardia_festiva(
                        franja_supervisor,
                        supervisores,
                        fecha_dia,
                        bloqueos,
                        avisos,
                        supervisor=True,
                        descartar_manuales=descartar_manuales,
                    )

    empleados_con_novedad = Empleado.objects.in_bulk(bloqueos.keys())
    for empleado_id, bloqueos_empleado in bloqueos.items():
        empleado = empleados_con_novedad.get(empleado_id)
        if empleado is None:
            continue
        for indice, tipo_novedad in bloqueos_empleado.items():
            fecha_novedad = dias[indice]
            if (
                empleado.fecha_ingreso
                and fecha_novedad < empleado.fecha_ingreso
            ):
                continue
            turno = Turno.objects.filter(
                empleado=empleado, fecha=fecha_novedad
            ).first()
            if turno:
                Turno.objects.update_or_create(
                    empleado=empleado,
                    fecha=fecha_novedad,
                    defaults=_datos_turno(
                        turno.franja, fecha_novedad, tipo_novedad
                    ),
                )

    return avisos


@transaction.atomic
def regenerar_rango(inicio, fin, max_semanas=60):
    """Recalcula las semanas YA generadas que tocan el rango inicio..fin.

    Devuelve (avisos, cantidad_de_semanas_recalculadas).
    """
    avisos = []
    recalculadas = 0
    lunes = lunes_de(inicio)
    for _ in range(max_semanas):
        if lunes > fin:
            break
        domingo = lunes + timedelta(days=6)
        if Turno.objects.filter(fecha__range=(lunes, domingo)).exists():
            for aviso in generar_semana(lunes):
                avisos.append(f"Semana del {lunes:%d/%m}: {aviso}")
            recalculadas += 1
        lunes += timedelta(days=7)
    return avisos, recalculadas


# ---------------------------------------------------------------
# Edición manual
# ---------------------------------------------------------------

def dia_descanso(empleado, fecha):
    """Fecha en que el empleado descansa en la semana de `fecha` (o None)."""
    turno = Turno.objects.filter(
        empleado=empleado, fecha__in=_dias_de_semana(fecha), descanso=True
    ).first()
    return turno.fecha if turno else None


def _revisar_cobertura(deltas):
    """deltas: {(franja_id, fecha): cambio en cuántos trabajan}. Devuelve los problemas."""
    problemas = []
    for (franja_id, fecha), delta in sorted(
        deltas.items(), key=lambda par: (par[0][1], par[0][0])
    ):
        if delta >= 0:
            continue   # solo preocupan los días en que trabaja menos gente
        franja = Franja.objects.select_related('rol').get(pk=franja_id)
        trabajan = Turno.objects.filter(
            franja=franja, fecha=fecha, descanso=False, novedad='',
            empleado__activo=True,
        ).count()
        quedarian = trabajan + delta
        if quedarian < franja.minimo_personas:
            problemas.append(
                f"{franja.rol.nombre} · {franja.nombre}: el {NOMBRES_DIA[fecha.weekday()]} "
                f"quedarían {quedarian} y se necesitan {franja.minimo_personas}."
            )
    return problemas


def _verificar_horas(empleado, fecha):
    """Comprueba que la semana tenga un solo descanso y las horas que corresponden."""
    turnos = list(Turno.objects.filter(
        empleado=empleado, fecha__in=_dias_de_semana(fecha)
    ))
    novedades = sum(1 for t in turnos if t.novedad)
    descansos = sum(1 for t in turnos if t.descanso)
    trabajados = sum(1 for t in turnos if not t.descanso and not t.novedad)

    horas = trabajados * empleado.rol.horas_por_dia
    esperado = max(0, 6 - novedades) * empleado.rol.horas_por_dia
    if descansos != 1 or horas != esperado:
        raise CambioInvalido(
            f"{empleado.nombre} quedaría con {horas} h y debe tener {esperado} h."
        )


@transaction.atomic
def cambiar_franja_tecnico(empleado, fecha, franja_id, forzar=False):
    """Cambia la franja del técnico en los turnos generados de toda la semana."""
    if empleado.rol.nombre.casefold().replace('é', 'e') != 'tecnico':
        raise CambioInvalido("Esta opción solo está disponible para técnicos.")
    if empleado.fecha_ingreso and fecha < empleado.fecha_ingreso:
        raise CambioInvalido(
            "La fecha seleccionada es anterior al ingreso del técnico."
        )

    franja_nueva = Franja.objects.select_related('rol').filter(
        pk=franja_id, rol_id=empleado.rol_id
    ).first()
    if franja_nueva is None:
        raise CambioInvalido("La franja seleccionada no pertenece al rol del técnico.")

    lunes = lunes_de(fecha)
    turnos = list(
        Turno.objects.select_related('franja')
        .filter(empleado=empleado, fecha__range=(lunes, lunes + timedelta(days=6)))
        .order_by('fecha')
    )
    if not turnos:
        raise CambioInvalido(
            f"{empleado.nombre} no tiene turnos generados en esa semana."
        )

    deltas = defaultdict(int)
    for turno in turnos:
        if turno.descanso or turno.novedad or not turno.inicio:
            continue
        if turno.franja_id == franja_nueva.id:
            continue
        if turno.franja_id:
            deltas[(turno.franja_id, turno.fecha)] -= 1
        deltas[(franja_nueva.id, turno.fecha)] += 1

    if not forzar:
        problemas = _revisar_cobertura(deltas)
        if problemas:
            raise CoberturaInsuficiente(problemas)

    for turno in turnos:
        turno.franja = franja_nueva
        if not turno.descanso and not turno.novedad and turno.inicio:
            entrada = datetime.combine(turno.fecha, franja_nueva.hora_inicio)
            salida = entrada + timedelta(hours=franja_nueva.rol.horas_por_dia)
            turno.inicio = entrada.time()
            turno.fin = salida.time()
        turno.manual = True
        turno.save(update_fields=[
            'franja', 'inicio', 'fin', 'manual',
        ])


def _reemplazar_permiso_por_descanso(empleado, fecha):
    permisos = list(Novedad.objects.filter(
        empleado=empleado,
        tipo='PERMISO',
        fecha_inicio__lte=fecha,
        fecha_fin__gte=fecha,
    ))
    if not permisos:
        raise CambioInvalido(
            "No se encontró el permiso que se debe reemplazar por el descanso."
        )
    if Novedad.objects.filter(
        empleado=empleado,
        fecha_inicio__lte=fecha,
        fecha_fin__gte=fecha,
    ).exclude(tipo='PERMISO').exists():
        raise CambioInvalido(
            "Ese día también tiene otra novedad y no se puede reemplazar."
        )

    for permiso in permisos:
        if permiso.fecha_inicio == fecha and permiso.fecha_fin == fecha:
            permiso.delete()
        elif permiso.fecha_inicio == fecha:
            permiso.fecha_inicio = fecha + timedelta(days=1)
            permiso.save(update_fields=['fecha_inicio'])
        elif permiso.fecha_fin == fecha:
            permiso.fecha_fin = fecha - timedelta(days=1)
            permiso.save(update_fields=['fecha_fin'])
        else:
            Novedad.objects.create(
                empleado=permiso.empleado,
                tipo=permiso.tipo,
                fecha_inicio=fecha + timedelta(days=1),
                fecha_fin=permiso.fecha_fin,
                nota=permiso.nota,
            )
            permiso.fecha_fin = fecha - timedelta(days=1)
            permiso.save(update_fields=['fecha_fin'])


@transaction.atomic
def cambiar_descansos(cambios, forzar=False):
    """cambios: lista de (empleado, nueva_fecha_de_descanso).

    Mueve el descanso de cada empleado a la fecha indicada. El día de descanso
    anterior pasa a ser de trabajo. Si algo falla, no se guarda nada.
    """
    preparados = []
    deltas = defaultdict(int)

    for emp, nueva in cambios:
        turnos = {
            t.fecha: t
            for t in Turno.objects.select_related('franja__rol')
            .filter(empleado=emp, fecha__in=_dias_de_semana(nueva))
        }
        if len(turnos) < 7:
            raise CambioInvalido(
                f"{emp.nombre} no tiene turnos generados en esa semana. Genera la semana primero."
            )
        viejo = next((t for t in turnos.values() if t.descanso), None)
        if viejo is None:
            raise CambioInvalido(f"{emp.nombre} no tiene día de descanso en esa semana.")
        if viejo.fecha == nueva:
            raise CambioInvalido(f"{emp.nombre} ya descansa ese día.")
        destino = turnos[nueva]
        reemplazar_permiso = destino.novedad == 'PERMISO'
        if destino.novedad and not reemplazar_permiso:
            tipo = dict(Novedad.TIPOS).get(destino.novedad, destino.novedad)
            raise CambioInvalido(f"{emp.nombre} ya tiene una novedad ese día ({tipo}).")
        franja = viejo.franja or emp.franja
        if franja is None:
            raise CambioInvalido(f"{emp.nombre} no tiene franja asignada.")

        preparados.append((emp, viejo, destino, franja, reemplazar_permiso))
        deltas[(franja.id, viejo.fecha)] += 1    # ese día vuelve a trabajar
        if not reemplazar_permiso:
            deltas[(franja.id, nueva)] -= 1      # ese día deja de trabajar

    if not forzar:
        problemas = _revisar_cobertura(deltas)
        if problemas:
            raise CoberturaInsuficiente(problemas)

    preferencias_festivas = {}
    supervisores_a_excluir = defaultdict(set)
    for emp, viejo, nuevo, franja, reemplazar_permiso in preparados:
        if reemplazar_permiso:
            _reemplazar_permiso_por_descanso(emp, nuevo.fecha)
        es_guardia_festiva = (
            _es_supervisor(emp) and viejo.fecha in FESTIVOS_COLOMBIA_2026
        )
        entrada = datetime.combine(
            viejo.fecha,
            time(6) if es_guardia_festiva else franja.hora_inicio,
        )
        salida = entrada + timedelta(
            hours=12 if es_guardia_festiva else franja.rol.horas_por_dia
        )

        viejo.descanso, viejo.inicio, viejo.fin = False, entrada.time(), salida.time()
        viejo.remoto = es_guardia_festiva
        viejo.manual = True
        viejo.save(update_fields=[
            'descanso', 'inicio', 'fin', 'remoto', 'manual',
        ])

        nuevo.descanso, nuevo.inicio, nuevo.fin = True, None, None
        nuevo.remoto = False
        if reemplazar_permiso:
            nuevo.novedad = ''
        nuevo.manual = True
        nuevo.save(update_fields=[
            'descanso', 'inicio', 'fin', 'remoto', 'novedad', 'manual',
        ])
        if viejo.fecha in FESTIVOS_COLOMBIA_2026 and _es_supervisor(emp):
            preferencias_festivas[viejo.fecha] = emp
        if nuevo.fecha in FESTIVOS_COLOMBIA_2026 and _es_supervisor(emp):
            supervisores_a_excluir[nuevo.fecha].add(emp.id)

    # Si algo no cuadra, el @transaction.atomic deshace todo
    for emp, viejo, nuevo, franja, _ in preparados:
        _verificar_horas(emp, viejo.fecha)
    for fecha_festiva in (
        set(preferencias_festivas) | set(supervisores_a_excluir)
    ):
        preferido = preferencias_festivas.get(fecha_festiva)
        excluidos = supervisores_a_excluir[fecha_festiva]
        if preferido and preferido.id in excluidos:
            preferido = None
        _asignar_guardia_festiva_supervisores(
            fecha_festiva,
            preferido=preferido,
            excluir=excluidos,
        )


@transaction.atomic
def agregar_descanso(empleado, fecha, forzar=False):
    """Marca otro día como descanso y conserva los descansos ya existentes."""
    dias = _dias_de_semana(fecha)
    turnos = {
        turno.fecha: turno
        for turno in Turno.objects.select_related('franja__rol').filter(
            empleado=empleado, fecha__in=dias
        )
    }
    if len(turnos) < 7:
        raise CambioInvalido(
            f"{empleado.nombre} no tiene turnos generados en esa semana. "
            "Genera la semana primero."
        )
    turno = turnos[fecha]
    if turno.descanso:
        raise CambioInvalido(f"{empleado.nombre} ya descansa ese día.")
    reemplazar_permiso = turno.novedad == 'PERMISO'
    if turno.novedad and not reemplazar_permiso:
        tipo = dict(Novedad.TIPOS).get(turno.novedad, turno.novedad)
        raise CambioInvalido(
            f"{empleado.nombre} tiene una novedad ese día ({tipo})."
        )
    franja = turno.franja or empleado.franja
    if franja is None:
        raise CambioInvalido(f"{empleado.nombre} no tiene franja asignada.")

    if not reemplazar_permiso and not forzar:
        problemas = _revisar_cobertura({(franja.id, fecha): -1})
        if problemas:
            raise CoberturaInsuficiente(problemas)
    if reemplazar_permiso:
        _reemplazar_permiso_por_descanso(empleado, fecha)

    turno.descanso = True
    turno.inicio = None
    turno.fin = None
    turno.remoto = False
    turno.novedad = ''
    turno.trabajar_sin_descanso_semanal = False
    turno.manual = True
    turno.save(update_fields=[
        'descanso', 'inicio', 'fin', 'remoto', 'novedad', 'manual',
        'trabajar_sin_descanso_semanal',
    ])
    if _es_supervisor(empleado) and fecha in FESTIVOS_COLOMBIA_2026:
        _asignar_guardia_festiva_supervisores(
            fecha,
            excluir=(empleado.id,),
        )


@transaction.atomic
def convertir_descanso_en_trabajo(empleado, fecha):
    """Convierte el descanso a trabajo sin asignar otro descanso esa semana."""
    turno = Turno.objects.select_related('franja__rol').filter(
        empleado=empleado, fecha=fecha
    ).first()
    if turno is None:
        raise CambioInvalido(
            f"{empleado.nombre} no tiene turno generado para esa fecha."
        )
    if not turno.descanso or turno.novedad:
        raise CambioInvalido(
            "Solo se puede convertir en trabajo un día marcado como descanso."
        )
    franja = turno.franja or empleado.franja
    if franja is None:
        raise CambioInvalido(f"{empleado.nombre} no tiene franja asignada.")

    es_guardia_festiva = (
        _es_supervisor(empleado) and fecha in FESTIVOS_COLOMBIA_2026
    )
    inicio = time(6) if es_guardia_festiva else franja.hora_inicio
    duracion = 12 if es_guardia_festiva else franja.rol.horas_por_dia
    turno.descanso = False
    turno.inicio = inicio
    turno.fin = (
        datetime.combine(fecha, inicio) + timedelta(hours=duracion)
    ).time()
    turno.remoto = es_guardia_festiva
    turno.manual = True
    turno.trabajar_sin_descanso_semanal = True
    turno.save(update_fields=[
        'descanso', 'inicio', 'fin', 'remoto', 'manual',
        'trabajar_sin_descanso_semanal',
    ])
    if es_guardia_festiva:
        _asignar_guardia_festiva_supervisores(fecha, preferido=empleado)


@transaction.atomic
def cambiar_horario(empleado, fecha, inicio):
    """Cambia la hora de inicio de un turno y conserva el ajuste al regenerar."""
    turno = Turno.objects.select_related('empleado__rol').filter(
        empleado=empleado, fecha=fecha
    ).first()
    if turno is None:
        raise CambioInvalido(
            f"{empleado.nombre} no tiene turno generado para esa fecha."
        )
    if turno.novedad:
        tipo = dict(Novedad.TIPOS).get(turno.novedad, turno.novedad)
        raise CambioInvalido(
            f"No se puede cambiar el horario porque tiene una novedad ({tipo})."
        )
    if turno.descanso or turno.inicio is None or turno.fin is None:
        raise CambioInvalido(
            "Solo se puede cambiar la hora de un turno de trabajo."
        )

    if _es_supervisor(empleado) and fecha in FESTIVOS_COLOMBIA_2026:
        turno.inicio = time(6)
        turno.fin = time(18)
        turno.remoto = True
        turno.manual = True
        turno.save(update_fields=['inicio', 'fin', 'remoto', 'manual'])
        return

    entrada_original = datetime.combine(fecha, turno.inicio)
    salida_original = datetime.combine(fecha, turno.fin)
    duracion = (salida_original - entrada_original).total_seconds() / 3600
    if duracion <= 0:
        duracion += 24
    entrada = datetime.combine(fecha, inicio)
    salida = entrada + timedelta(hours=duracion)
    turno.inicio = entrada.time()
    turno.fin = salida.time()
    turno.manual = True
    turno.save(update_fields=['inicio', 'fin', 'manual'])


@transaction.atomic
def intercambiar_fin_de_semana_supervisores(a, b, fecha):
    """Intercambia los patrones de sábado/domingo entre dos supervisores."""
    if a.pk == b.pk:
        raise CambioInvalido("Elige a un supervisor distinto.")
    if (
        a.rol_id != b.rol_id
        or a.rol.nombre.casefold() != 'supervisor'
        or b.rol.nombre.casefold() != 'supervisor'
    ):
        raise CambioInvalido(
            "Solo se pueden intercambiar fines de semana entre supervisores."
        )

    supervisores = list(
        Empleado.objects.filter(activo=True, rol__nombre__iexact='Supervisor')
        .order_by('id')
    )
    if len(supervisores) != 4 or a.pk not in {e.pk for e in supervisores} or b.pk not in {
        e.pk for e in supervisores
    }:
        raise CambioInvalido(
            "El intercambio requiere exactamente cuatro supervisores activos."
        )

    sabado = lunes_de(fecha) + timedelta(days=5)
    domingo = sabado + timedelta(days=1)
    turnos = {
        emp.pk: {
            turno.fecha: turno
            for turno in Turno.objects.filter(
                empleado=emp, fecha__in=(sabado, domingo)
            ).select_related('franja')
        }
        for emp in supervisores
    }
    if any(len(turnos[emp.pk]) != 2 for emp in supervisores):
        raise CambioInvalido(
            "Genera los turnos de la semana antes de intercambiar el fin de semana."
        )
    if any(
        not _turno_fin_semana_intercambiable(turno, turno.fecha.weekday())
        for turnos_empleado in turnos.values()
        for turno in turnos_empleado.values()
    ):
        raise CambioInvalido(
            "No se puede intercambiar: revisa las novedades o los datos de los "
            "turnos del fin de semana."
        )

    afectados = (a, b)
    for emp in afectados:
        for turno in turnos[emp.pk].values():
            if turno.novedad:
                tipo = dict(Novedad.TIPOS).get(turno.novedad, turno.novedad)
                raise CambioInvalido(
                    f"No se puede intercambiar el fin de semana de {emp.nombre}: "
                    f"tiene una novedad ({tipo})."
                )

    patrones = {
        emp.pk: {
            dia: not turnos[emp.pk][dia].descanso
            for dia in (sabado, domingo)
        }
        for emp in supervisores
    }
    libres_completos = sum(
        not patron[sabado] and not patron[domingo]
        for patron in patrones.values()
    )
    sabado_cubierto = sum(patron[sabado] for patron in patrones.values())
    domingo_cubierto = sum(patron[domingo] for patron in patrones.values())
    if (libres_completos, sabado_cubierto, domingo_cubierto) != (2, 1, 1):
        raise CambioInvalido(
            "El fin de semana debe tener dos supervisores libres ambos días, "
            "uno trabajando el sábado y uno el domingo."
        )
    if patrones[a.pk] == patrones[b.pk]:
        raise CambioInvalido("Los dos supervisores ya tienen el mismo patrón.")

    patrones[a.pk], patrones[b.pk] = patrones[b.pk], patrones[a.pk]
    for emp in afectados:
        for dia in (sabado, domingo):
            turno = turnos[emp.pk][dia]
            trabaja = patrones[emp.pk][dia]
            if trabaja:
                entrada = datetime.strptime('06:00', '%H:%M').time()
                salida = datetime.strptime('18:00', '%H:%M').time()
                turno.descanso = False
                turno.inicio = entrada
                turno.fin = salida
                turno.remoto = dia == domingo
            else:
                turno.descanso = True
                turno.inicio = None
                turno.fin = None
                turno.remoto = False
            turno.manual = True
            turno.save(update_fields=[
                'descanso', 'inicio', 'fin', 'remoto', 'manual',
            ])


def intercambiar_descansos(a, b, fecha, forzar=False):
    """Intercambia los días de descanso de dos personas del mismo rol."""
    if a.pk == b.pk:
        raise CambioInvalido("Elige a un compañero distinto.")
    if a.rol_id != b.rol_id:
        raise CambioInvalido("Solo se pueden intercambiar descansos entre personas del mismo rol.")

    da = dia_descanso(a, fecha)
    db = dia_descanso(b, fecha)
    if da is None or db is None:
        raise CambioInvalido("Las dos personas deben tener turnos generados en esa semana.")
    if da == db:
        raise CambioInvalido("Las dos personas ya descansan el mismo día.")

    cambiar_descansos([(a, db), (b, da)], forzar=forzar)
