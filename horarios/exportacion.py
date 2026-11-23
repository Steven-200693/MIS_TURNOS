from datetime import date, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import escape


PLANTILLA_PARTE = (
    Path(__file__).resolve().parent
    / 'plantillas'
    / 'Plantilla Parte Trabajov2.xlsx'
)

PROYECTO = 'OP01| OPERADORA HOSPITAL BOSA'
CENTRO_COSTE = 'OP0101.01.07.03.03| TECNICOS'


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

    inicio_ventana = datetime.combine(fecha, time(18))
    fin_ventana = datetime.combine(fecha + timedelta(days=1), time(6))
    inicio = max(inicio_turno, inicio_ventana)
    fin = min(fin_turno, fin_ventana)
    if fin <= inicio:
        return 0
    return round((fin - inicio).total_seconds() / 3600, 2)


def _celda_texto_xml(columna, fila, valor):
    return (
        f'<c r="{columna}{fila}" t="inlineStr"><is>'
        f'<t xml:space="preserve">{escape(valor)}</t></is></c>'
    )


def _fila_parte_xml(numero, empleado, horas):
    nombre_empleado = (
        f'{empleado.numero_recurso}| {empleado.nombre.upper()}'
    )
    return (
        f'<row r="{numero}" spans="1:18">'
        f'{_celda_texto_xml("A", numero, nombre_empleado)}'
        f'<c r="G{numero}"><v>{horas}</v></c>'
        f'{_celda_texto_xml("O", numero, PROYECTO)}'
        f'{_celda_texto_xml("P", numero, CENTRO_COSTE)}'
        '</row>'
    )


def _insertar_filas_parte(xml, filas):
    if not filas:
        return xml

    dimension = re.search(
        r'<dimension ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"\s*/>',
        xml,
    )
    if dimension is None:
        raise ValueError('La plantilla de partes no tiene una dimensión válida.')

    inicio = xml.index('<sheetData>')
    fin = xml.index('</sheetData>', inicio)
    datos = xml[inicio + len('<sheetData>'):fin]

    def desplazar_fila(match):
        numero = int(match.group(2))
        if numero > 1:
            numero += len(filas)
        return f'{match.group(1)}{numero}{match.group(3)}'

    datos = re.sub(
        r'(<row\b[^>]*?\br=")(\d+)(")',
        desplazar_fila,
        datos,
    )
    fin_encabezado = datos.find('</row>')
    if fin_encabezado == -1:
        raise ValueError('La plantilla de partes no tiene una fila de encabezado.')
    fin_encabezado += len('</row>')
    nuevas_filas = ''.join(
        _fila_parte_xml(numero, empleado, horas)
        for numero, empleado, horas in filas
    )
    datos = datos[:fin_encabezado] + nuevas_filas + datos[fin_encabezado:]
    xml = xml[:inicio + len('<sheetData>')] + datos + xml[fin:]

    dimension_actualizada = (
        f'<dimension ref="{dimension.group(1)}{dimension.group(2)}:'
        f'{dimension.group(3)}{int(dimension.group(4)) + len(filas)}"/>'
    )
    return xml[:dimension.start()] + dimension_actualizada + xml[dimension.end():]


def crear_excel_diario(fecha, empleados, turnos):
    turnos_por_empleado = {turno.empleado_id: turno for turno in turnos}
    filas = []
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
        if not horas:
            continue
        filas.append((len(filas) + 2, empleado, horas))

    salida = BytesIO()
    with ZipFile(PLANTILLA_PARTE, 'r') as plantilla:
        xml_parte = plantilla.read(
            'xl/worksheets/sheet1.xml'
        ).decode('utf-8')
        xml_parte = _insertar_filas_parte(xml_parte, filas)
        with ZipFile(salida, 'w', compression=ZIP_DEFLATED) as libro:
            libro.comment = plantilla.comment
            for entrada in plantilla.infolist():
                contenido = (
                    xml_parte.encode('utf-8')
                    if entrada.filename == 'xl/worksheets/sheet1.xml'
                    else plantilla.read(entrada.filename)
                )
                libro.writestr(entrada, contenido)
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
