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


def _asignaciones_supervisores(lunes):
    """Rota equitativamente los supervisores por las franjas de su rol."""
    supervisores = list(
        Empleado.objects.filter(
            activo=True, rol__nombre__iexact='Supervisor'
        ).order_by('id')
    )
    franjas = list(
        Franja.objects.filter(rol__nombre__iexact='Supervisor')
        .select_related('rol').order_by('hora_inicio', 'id')
    )
    if len(supervisores) != 4 or len(franjas) != 4:
        return {}, set(), bool(supervisores)

    semana_ancla = date(2000, 1, 3)
    numero_semana = (lunes - semana_ancla).days // 7
    asignaciones = {franja.id: set() for franja in franjas}
    for indice, supervisor in enumerate(supervisores):
        franja = franjas[(indice + numero_semana) % len(franjas)]
        asignaciones[franja.id].add(supervisor.id)
    return asignaciones, {supervisor.rol_id for supervisor in supervisores}, False


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
    cupo_noche_minimo = max(0, 2 - tecnicos_noche_fijos)

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
    asignaciones_supervisores, roles_supervisores, franjas_supervisores_faltantes = (
        _asignaciones_supervisores(lunes)
    )
    asignaciones_tecnicos, roles_tecnicos_sin_franja, franjas_tecnicas_faltantes = (
        _asignaciones_tecnicos_sin_franja(lunes)
    )
    politica_supervisores = len(asignaciones_fin_de_semana) == 4
    if not politica_supervisores and total_supervisores:
        avisos.append(
            'La rotación de fin de semana requiere exactamente cuatro supervisores '
            'activos; se conservaron sus turnos habituales.'
        )
    if franjas_supervisores_faltantes:
        avisos.append(
            'La rotación de franjas de supervisores requiere exactamente cuatro '
            'supervisores activos y cuatro franjas de Supervisor.'
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

    # Descansos fijados a mano: empleado_id -> índice del día (0 = lunes)
    fijos = {
        t.empleado_id: (t.fecha - lunes).days
        for t in Turno.objects.filter(fecha__in=dias, manual=True, descanso=True)
    }
    turnos_manuales = {
        (t.empleado_id, (t.fecha - lunes).days): t
        for t in Turno.objects.filter(fecha__in=dias, manual=True)
    }

    for franja in Franja.objects.select_related('rol'):
        etiqueta = f"{franja.rol.nombre} · {franja.nombre}"
        if franja.rol_id in roles_supervisores:
            seleccion_empleados = Q(
                pk__in=asignaciones_supervisores.get(franja.id, set())
            )
        elif franja.rol_id in roles_tecnicos_sin_franja:
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
            preferidos = DIAS_PERMITIDOS[emp.preferencia_descanso]
            manuales_emp = {
                dia for (empleado_id, dia) in turnos_manuales
                if empleado_id == emp.id and dia not in bloq
            }
            candidatos = [
                d for d in preferidos if d not in bloq and d not in manuales_emp
            ]
            if not candidatos:
                candidatos = [
                    d for d in range(7) if d not in bloq and d not in manuales_emp
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
                if emp.id in fijos and fijos[emp.id] not in bloqueos.get(emp.id, {})
            }
            dias_rotacion = [6, 5, 4, 3, 2, 1, 0]
            for emp in equipo:
                if emp.id in fijos:
                    continue
                bloq = bloqueos.get(emp.id, {})
                disponibles = [
                    dia for dia in dias_rotacion
                    if dia not in descansos_ocupados
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
                    novedad = bloqueos.get(emp.id, {}).get(dia)
                    if novedad:
                        continue
                    existente = Turno.objects.filter(
                        empleado=emp, fecha=dias[dia]
                    ).first()
                    if existente and existente.manual and not descartar_manuales:
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

        # 4) Revisar la cobertura de la franja, día por día
        for d in range(7):
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
        if destino.novedad:
            tipo = dict(Novedad.TIPOS).get(destino.novedad, destino.novedad)
            raise CambioInvalido(f"{emp.nombre} ya tiene una novedad ese día ({tipo}).")
        franja = viejo.franja or emp.franja
        if franja is None:
            raise CambioInvalido(f"{emp.nombre} no tiene franja asignada.")

        preparados.append((emp, viejo, destino, franja))
        deltas[(franja.id, viejo.fecha)] += 1    # ese día vuelve a trabajar
        deltas[(franja.id, nueva)] -= 1          # ese día deja de trabajar

    if not forzar:
        problemas = _revisar_cobertura(deltas)
        if problemas:
            raise CoberturaInsuficiente(problemas)

    for emp, viejo, nuevo, franja in preparados:
        entrada = datetime.combine(viejo.fecha, franja.hora_inicio)
        salida = entrada + timedelta(hours=franja.rol.horas_por_dia)

        viejo.descanso, viejo.inicio, viejo.fin = False, entrada.time(), salida.time()
        viejo.manual = True
        viejo.save()

        nuevo.descanso, nuevo.inicio, nuevo.fin = True, None, None
        nuevo.manual = True
        nuevo.save()

    # Si algo no cuadra, el @transaction.atomic deshace todo
    for emp, viejo, nuevo, franja in preparados:
        _verificar_horas(emp, viejo.fecha)


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
