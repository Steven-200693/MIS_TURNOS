from datetime import date, datetime, time, timedelta
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.styles.colors import Color


ENCABEZADOS_PARTE = (
    'No. Recurso',
    'Control de partes',
    'Horas ordinarias',
    'Horas ordinarias Dom/Fest',
    'Horas extras diurnas',
    'Horas extras nocturnas',
    'Recargo hora nocturna ord',
    'Horas extras diurnas Dom/Fest',
    'Horas extras noct. Dom/Fest',
    'Recargo hora noc Dom/Fest',
    'Hora Diurna Ord. Dom/Fest c/Comp',
    'Hora Diurna Ord. Dom/Fest s/Comp',
    'Hora Noct. Ord. Dom/Fest c/Comp',
    'Hora Noct. Ord. Dom/Fest s/Comp',
    'No. Proyecto',
    'Centro de coste',
    'Ausente',
    'Motivo ausencia',
)

PROYECTO = 'OP01| OPERADORA HOSPITAL BOSA'
CENTRO_COSTE = 'OP0101.01.07.03.03| TECNICOS'
MOTIVOS_AUSENCIA = (
    'ACCTRA| ACCIDENTE DE TRABAJO',
    'AUSIN| AUSENCIA INJUSTIFICADA',
    'COMPEN| COMPENSATORIO',
    'DCSO| DESCANSO',
    'INCEGRPRO| INCAPACIDAD ENF. PROFESIONAL',
    'INCGRL| INCAPACIDAD POR ENF. GENERAL',
    'INCGRL100| INCAPACIDAD ENF. GENERAL 100%',
    'LICLUTO| LICENCIA POR LUTO',
    'LICMAT| LICENCIA MATERNIDAD',
    'LICNOR| LICENCIA NO REMUNERADA',
    'LICPAT| LICENCIA PATERNIDAD',
    'LICREM| LICENCIA REMUNERADA',
    'SANDISC| SANCIÓN DISCIPLINARIA',
    'SUSCTO| SUSPENSION CTO POR FUERZA MAYOR',
    'SUSP| SUSPENSIONES',
    'VACDIS| VACACIONES DISFRUTADAS',
    'VACPAG| VACACIONES COMPENSADAS DINERO',
)

ANCHO_COLUMNAS = {
    'A': 15.29,
    'B': 27.29,
    'C': 27.29,
    'K': 34.57,
    'L': 35.43,
    'M': 33.43,
    'N': 32.29,
    'O': 25.71,
    'P': 18.71,
    'Q': 11.43,
    'R': 15.71,
}


def rango_periodo_15_a_15(mes):
    if not isinstance(mes, str) or len(mes) != 7:
        raise ValueError('Indica el mes inicial con el formato AAAA-MM.')
    try:
        primer_dia = date.fromisoformat(f'{mes}-01')
    except ValueError as error:
        raise ValueError('Indica un mes válido con el formato AAAA-MM.') from error
    if primer_dia.strftime('%Y-%m') != mes:
        raise ValueError('Indica un mes válido con el formato AAAA-MM.')

    fecha_inicio = primer_dia.replace(day=15)
    if primer_dia.month == 12:
        fecha_fin = date(primer_dia.year + 1, 1, 15)
    else:
        fecha_fin = date(primer_dia.year, primer_dia.month + 1, 15)
    return fecha_inicio, fecha_fin


def horas_nocturnas(turno, fecha):
    if (
        turno.descanso
        or turno.novedad
        or turno.inicio is None
        or turno.fin is None
    ):
        return 0

    inicio_turno = datetime.combine(turno.fecha, turno.inicio)
    fin_turno = datetime.combine(turno.fecha, turno.fin)
    if fin_turno <= inicio_turno:
        fin_turno += timedelta(days=1)

    inicio_ventana = datetime.combine(fecha, time(19))
    fin_ventana = datetime.combine(fecha + timedelta(days=1), time(6))
    inicio = max(inicio_turno, inicio_ventana)
    fin = min(fin_turno, fin_ventana)
    if fin <= inicio:
        return 0
    return round((fin - inicio).total_seconds() / 3600, 2)


def _agregar_hojas_catalogo(libro, empleados):
    control = libro.create_sheet('Control de partes')
    control.append(['Parte diario'])
    control.append(['Parte en el periodo'])

    proyectos = libro.create_sheet('Proyectos')
    proyectos.append([PROYECTO])

    centros = libro.create_sheet('Centros de coste')
    centros.append([CENTRO_COSTE])

    trabajadores = libro.create_sheet('Trabajadores')
    for empleado in empleados:
        trabajadores.append([
            f'{empleado.numero_recurso}| {empleado.nombre.upper()}'
        ])

    ausencia = libro.create_sheet('Ausencia')
    ausencia.append(['Si'])
    ausencia.append(['No'])

    motivos = libro.create_sheet('Motivos ausencia')
    for motivo in MOTIVOS_AUSENCIA:
        motivos.append([motivo])


def crear_excel_diario(fecha, empleados, turnos):
    libro = Workbook()
    hoja = libro.active
    hoja.title = 'Parte'
    hoja.append(ENCABEZADOS_PARTE)
    hoja.row_dimensions[1].height = 29.45

    relleno_encabezado = PatternFill(
        fill_type='solid',
        fgColor=Color(theme=5, tint=0.5999938962981048),
    )
    for celda in hoja[1]:
        celda.fill = relleno_encabezado
        celda.font = Font(name='Calibri', size=11)
        celda.alignment = Alignment(
            horizontal='center',
            vertical='top',
            wrap_text=True,
        )
    hoja['R1'].number_format = '@'
    for columna, ancho in ANCHO_COLUMNAS.items():
        hoja.column_dimensions[columna].width = ancho

    turnos_por_empleado = {turno.empleado_id: turno for turno in turnos}
    for empleado in empleados:
        turno = turnos_por_empleado.get(empleado.id)
        if (
            turno is None
            or turno.descanso
            or turno.novedad
            or turno.inicio is None
            or turno.fin is None
        ):
            continue
        horas = horas_nocturnas(turno, fecha)
        fila = [None] * len(ENCABEZADOS_PARTE)
        fila[0] = f'{empleado.numero_recurso}| {empleado.nombre.upper()}'
        if horas:
            fila[6] = horas
        fila[14] = PROYECTO
        fila[15] = CENTRO_COSTE
        hoja.append(fila)

    _agregar_hojas_catalogo(libro, empleados)
    libro.properties.title = f'Parte de trabajo {fecha:%d-%m-%Y}'
    libro.properties.subject = f'Parte diario del {fecha:%d/%m/%Y}'

    salida = BytesIO()
    libro.save(salida)
    return salida.getvalue()


def crear_zip_partes(fecha_inicio, fecha_fin, empleados, turnos):
    turnos_por_fecha = {}
    for turno in turnos:
        turnos_por_fecha.setdefault(turno.fecha, []).append(turno)

    salida = BytesIO()
    with ZipFile(salida, 'w', compression=ZIP_DEFLATED) as archivo_zip:
        fecha = fecha_inicio
        while fecha <= fecha_fin:
            contenido = crear_excel_diario(
                fecha,
                empleados,
                turnos_por_fecha.get(fecha, []),
            )
            archivo_zip.writestr(
                f'Parte-Trabajo-{fecha.isoformat()}.xlsx',
                contenido,
            )
            fecha += timedelta(days=1)
    return salida.getvalue()
