// =====================================================================
// BLOQUE A: Constantes, elementos de la página y estado
// =====================================================================
const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
               'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const NOVEDADES = {
  COMPENSATORIO: { texto: 'Compensatorio', clases: 'bg-emerald-200 text-emerald-900' },
  INCAPACIDAD: { texto: 'Incapacidad', clases: 'bg-rose-200 text-rose-900' },
  VACACIONES: { texto: 'Vacaciones', clases: 'bg-sky-200 text-sky-900' },
  PERMISO: { texto: 'Permiso', clases: 'bg-violet-200 text-violet-900' },
};

const COLORES_TURNO = {
  '06:00': '#fef08a',
  '09:00': '#fef08a',
  '12:00': '#fef08a',
  '13:00': '#bbf7d0',
  '16:00': '#60a5fa',
  '23:00': '#111827',
};

const $tabla = document.getElementById('tabla');
const $rango = document.getElementById('rango');
const $info = document.getElementById('info');
const $avisos = document.getElementById('avisos');
const $dashboardDescansos = document.getElementById('dashboard-descansos');
const $dashboardPeriodo = document.getElementById('dashboard-descansos-periodo');
const $actaMes = document.getElementById('acta-retribucion-mes');
const $actaAsignado = document.getElementById('acta-retribucion-asignado');
const $actaControles = document.getElementById('acta-retribucion-controles');
const $actaSupervisor = document.getElementById('acta-retribucion-supervisor');
const $actaGuardar = document.getElementById('acta-retribucion-guardar');
const $actaMensaje = document.getElementById('acta-retribucion-mensaje');
const $btnGenerar = document.getElementById('btn-generar');
const $btnDescartar = document.getElementById('btn-descartar');
const $btnLimpiar = document.getElementById('btn-limpiar');
const $btnCopiarImagen = document.getElementById('btn-copiar-imagen');
const $btnExportarExcel = document.getElementById('btn-exportar-excel');
const $distribucionTecnicos = document.getElementById('distribucion-tecnicos');
const $distribucionResumen = document.getElementById('distribucion-resumen');
const $btnGuardarDistribucion = document.getElementById('btn-guardar-distribucion');
const $leyendaFranjas = document.getElementById('leyenda-franjas');

const ES_ADMIN = document.body.dataset.admin === '1';

// Fecha que se está mostrando, como texto 'AAAA-MM-DD'
let fechaActual = aTexto(new Date());
let datosSemana = null;   // última respuesta de /api/semana/


// =====================================================================
// BLOQUE B: Funciones de apoyo
// =====================================================================

// Date -> '2026-10-21' (usando la hora local, no UTC)
function aTexto(fecha) {
  const a = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${a}-${m}-${d}`;
}

// '2026-10-21' -> Date (a medianoche local)
function desdeTexto(texto) {
  const [a, m, d] = texto.split('-').map(Number);
  return new Date(a, m - 1, d);
}

// Suma o resta días a una fecha en texto
function sumarDias(texto, n) {
  const f = desdeTexto(texto);
  f.setDate(f.getDate() + n);
  return aTexto(f);
}

// Crea un elemento HTML con clases y texto
function el(etiqueta, clases = '', texto = '') {
  const nodo = document.createElement(etiqueta);
  if (clases) nodo.className = clases;
  if (texto) nodo.textContent = texto;
  return nodo;
}

function leerCookie(nombre) {
  const par = document.cookie.split('; ').find(c => c.startsWith(nombre + '='));
  return par ? par.split('=')[1] : null;
}

// Igual que fetch, pero devuelve {ok, estado, datos} sin lanzar error
async function enviarJSON(url, cuerpo) {
  const respuesta = await fetch(url, {
    method: 'POST',
    headers: {
      'X-CSRFToken': leerCookie('csrftoken'),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(cuerpo),
  });
  const datos = await respuesta.json().catch(() => ({}));
  return { ok: respuesta.ok, estado: respuesta.status, datos };
}

// Fecha en que descansa un empleado en la semana mostrada (o null)
function diaDescanso(emp) {
  return Object.keys(emp.turnos).find(d => emp.turnos[d].descanso) || null;
}

function turnoGenerado(turno) {
  return Boolean(
    turno && (turno.descanso || turno.novedad || (turno.inicio && turno.fin))
  );
}

// '2026-10-21' -> 'Mié'
function nombreDia(fecha) {
  return DIAS[datosSemana.dias.indexOf(fecha)];
}

function normalizarRol(rol) {
  return rol.normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

function colorFranja(horaInicio, rol) {
  if (normalizarRol(rol) === 'supervisor') {
    if (horaInicio === '09:00') return '#fca5a5';
    if (horaInicio === '12:00') return '#bbf7d0';
  }
  return COLORES_TURNO[horaInicio] || '#f1f5f9';
}

function empleadosDelHorario() {
  return datosSemana.empleados
    .filter(empleado => ['tecnico', 'supervisor'].includes(normalizarRol(empleado.rol)))
    .map(empleado => ({
      ...empleado,
      franjaSemana: empleado.franja || 'Sin franja',
      turnosSemana: datosSemana.dias.map(fecha => empleado.turnos[fecha] || null),
    }));
}

function textoTurno(turno) {
  if (!turno) return '';
  if (turno.novedad) return NOVEDADES[turno.novedad]?.texto || turno.novedad;
  if (turno.descanso) return 'Descanso';
  if (!turno.inicio || !turno.fin) return '';
  const cruza = turno.fin < turno.inicio;
  const remoto = turno.remoto ? ' (DS)' : '';
  return `${turno.inicio}-${turno.fin}${cruza ? ' (+1)' : ''}${remoto}`;
}

function blobDelCanvas(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob);
      else reject(new Error('No se pudo generar la imagen del horario.'));
    }, 'image/png');
  });
}

function dibujarImagenHorario() {
  const empleados = empleadosDelHorario();
  const semanaInicio = desdeTexto(datosSemana.dias[0]);
  const semanaFin = desdeTexto(datosSemana.dias[6]);
  const escala = 2;
  const rolAncho = 120;
  const nombreAncho = 220;
  const diaAncho = 150;
  const ancho = rolAncho + nombreAncho + diaAncho * 7;
  const altoTitulo = 64;
  const altoCabecera = 54;
  const altoFila = 48;
  const canvas = document.createElement('canvas');
  canvas.width = ancho * escala;
  canvas.height = (altoTitulo + altoCabecera + altoFila * empleados.length) * escala;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('El navegador no pudo preparar el lienzo de imagen.');
  ctx.scale(escala, escala);
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, ancho, canvas.height / escala);

  ctx.fillStyle = '#0f172a';
  ctx.font = 'bold 22px Arial, sans-serif';
  ctx.fillText('Horario semanal', 16, 29);
  ctx.font = '14px Arial, sans-serif';
  ctx.fillStyle = '#475569';
  ctx.fillText(
    `${semanaInicio.getDate()}/${semanaInicio.getMonth() + 1}/${semanaInicio.getFullYear()} - ${semanaFin.getDate()}/${semanaFin.getMonth() + 1}/${semanaFin.getFullYear()}`,
    16,
    51,
  );

  const yCabecera = altoTitulo;
  ctx.fillStyle = '#e2e8f0';
  ctx.fillRect(0, yCabecera, ancho, altoCabecera);
  ctx.font = 'bold 13px Arial, sans-serif';
  ctx.fillStyle = '#1e293b';
  const titulos = [
    { texto: 'Rol', x: 0, ancho: rolAncho },
    { texto: 'Empleado', x: rolAncho, ancho: nombreAncho },
  ];
  titulos.forEach(item => {
    ctx.fillText(item.texto, item.x + 10, yCabecera + 31);
  });
  datosSemana.dias.forEach((fecha, indice) => {
    const dia = desdeTexto(fecha);
    const x = rolAncho + nombreAncho + diaAncho * indice;
    const festivo = datosSemana.festivos?.find(item => item.fecha === fecha);
    ctx.fillStyle = festivo ? '#92400e' : '#1e293b';
    ctx.fillText(
      `${DIAS[indice]} ${dia.getDate()}/${dia.getMonth() + 1}${festivo ? ' *' : ''}`,
      x + 8,
      yCabecera + 31,
    );
    if (festivo) {
      ctx.font = '10px Arial, sans-serif';
      ctx.fillText(festivo.nombre, x + 8, yCabecera + 45);
      ctx.font = 'bold 13px Arial, sans-serif';
    }
  });

  empleados.forEach((empleado, indiceEmpleado) => {
    const y = altoTitulo + altoCabecera + altoFila * indiceEmpleado;
    const colorRol = normalizarRol(empleado.rol) === 'tecnico' ? '#f8fafc' : '#f1f5f9';
    ctx.fillStyle = colorRol;
    ctx.fillRect(0, y, ancho, altoFila);
    ctx.fillStyle = '#334155';
    ctx.font = '12px Arial, sans-serif';
    ctx.fillText(empleado.rol, 10, y + 28);
    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 12px Arial, sans-serif';
    ctx.fillText(empleado.nombre, rolAncho + 10, y + 21, nombreAncho - 16);
    empleado.turnosSemana.forEach((turno, indiceDia) => {
      const x = rolAncho + nombreAncho + diaAncho * indiceDia;
      const fecha = datosSemana.dias[indiceDia];
      const festivo = datosSemana.festivos?.some(item => item.fecha === fecha);
      const franja = turno?.franja_id
        ? datosSemana.franjas.find(item => item.id === turno.franja_id)
        : null;
      const horaInicio = franja?.hora_inicio || turno?.inicio;
      let fondo = '#ffffff';
      if (turno?.novedad) {
        fondo = {
          COMPENSATORIO: '#a7f3d0',
          INCAPACIDAD: '#fecdd3',
          VACACIONES: '#bae6fd',
          PERMISO: '#ddd6fe',
        }[turno.novedad] || '#e2e8f0';
      } else if (turno?.descanso) {
        fondo = '#fde68a';
      } else if (turno?.inicio) {
        fondo = colorFranja(
          franja?.hora_inicio || turno.inicio,
          franja?.rol || empleado.rol,
        );
      } else if (festivo) {
        fondo = '#fffbeb';
      }
      ctx.fillStyle = fondo;
      ctx.fillRect(x, y, diaAncho, altoFila);
      ctx.fillStyle = horaInicio === '23:00' && !turno?.novedad && !turno?.descanso
        ? '#ffffff'
        : '#0f172a';
      ctx.font = '12px Arial, sans-serif';
      const contenido = textoTurno(turno);
      if (contenido) {
        ctx.fillText(contenido, x + 8, y + 27, diaAncho - 16);
      }
      if (festivo) {
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 2;
        ctx.strokeRect(x + 1, y + 1, diaAncho - 2, altoFila - 2);
      }
    });

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y + altoFila);
    ctx.lineTo(ancho, y + altoFila);
    ctx.stroke();
  });
  return canvas;
}

async function copiarImagenHorario() {
  if (!datosSemana) {
    mostrarError('Espera a que se cargue el horario antes de copiarlo.');
    return;
  }
  if (!empleadosDelHorario().length) {
    mostrarError('No hay técnicos ni supervisores para copiar en esta semana.');
    return;
  }
  if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
    mostrarError('Este navegador no permite copiar imágenes. Abre la aplicación en HTTPS o en localhost y prueba con un navegador actualizado.');
    return;
  }
  $btnCopiarImagen.disabled = true;
  try {
    const canvas = dibujarImagenHorario();
    const blob = await blobDelCanvas(canvas);
    await navigator.clipboard.write([
      new ClipboardItem({ 'image/png': blob }),
    ]);
    mostrarOk('La imagen completa del horario semanal se copió al portapapeles.');
  } catch (error) {
    mostrarError(`No se pudo copiar la imagen: ${error.message}`);
  } finally {
    $btnCopiarImagen.disabled = false;
  }
}

async function exportarExcelHorario() {
  if (!datosSemana) {
    mostrarError('Espera a que se cargue el horario antes de exportarlo.');
    return;
  }
  $btnExportarExcel.disabled = true;
  try {
    const respuesta = await fetch(
      `/api/semana/exportar-excel/?fecha=${encodeURIComponent(fechaActual)}`
    );
    if (!respuesta.ok) {
      const error = await respuesta.json().catch(() => ({}));
      throw new Error(error.error || `El servidor respondió ${respuesta.status}`);
    }
    const archivo = await respuesta.blob();
    const url = URL.createObjectURL(archivo);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = `horario-semana-${datosSemana.lunes}.xlsx`;
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    mostrarOk('Se descargó el archivo Excel con el horario de la semana.');
  } catch (error) {
    mostrarError(`No se pudo exportar el Excel: ${error.message}`);
  } finally {
    $btnExportarExcel.disabled = false;
  }
}

function actualizarResumenDistribucion(totalEsperado) {
  if (!$distribucionTecnicos) return;
  const inputs = [...$distribucionTecnicos.querySelectorAll('input[data-franja-id]')];
  const cantidades = inputs.map(input => Number(input.value));
  const suma = cantidades.reduce((total, cantidad) => total + cantidad, 0);
  const valida = inputs.every(input =>
    Number.isInteger(Number(input.value))
    && Number(input.value) >= Number(input.min)
  ) && suma === totalEsperado;
  $distribucionResumen.textContent =
    `Cupos seleccionados: ${suma} de ${totalEsperado} técnicos sin franja`;
  $distribucionResumen.className =
    `text-sm font-medium ${valida ? 'text-green-700' : 'text-red-700'}`;
  $btnGuardarDistribucion.disabled = !valida || inputs.length !== 4;
  return valida && inputs.length === 4;
}

function pintarDistribucionTecnicos(distribucion) {
  if (!$distribucionTecnicos || !$distribucionResumen || !$btnGuardarDistribucion) return;
  $distribucionTecnicos.replaceChildren();
  const franjas = distribucion.franjas || [];
  franjas.forEach(franja => {
    const etiqueta = el('label', 'block text-sm font-medium mb-1',
      `${franja.nombre} (${franja.hora_inicio})`);
    const entrada = document.createElement('input');
    entrada.type = 'number';
    entrada.min = String(franja.cantidad_minima || 0);
    entrada.max = String(distribucion.total);
    entrada.step = '1';
    entrada.required = true;
    entrada.value = String(franja.cantidad);
    entrada.dataset.franjaId = String(franja.id);
    entrada.className = 'w-full border border-slate-300 rounded px-3 py-2';
    entrada.addEventListener('input', () =>
      actualizarResumenDistribucion(distribucion.total));
    const campo = el('div', 'p-3 bg-slate-50 rounded');
    campo.append(etiqueta, entrada);
    $distribucionTecnicos.appendChild(campo);
  });
  const cuposValidos = actualizarResumenDistribucion(distribucion.total);
  if (distribucion.invalida && !cuposValidos) {
    $distribucionResumen.textContent =
      'La configuración anterior no coincide con el personal actual. Ajusta los cupos y guárdalos nuevamente.';
    $distribucionResumen.className = 'text-sm font-medium text-amber-700';
  }
  $btnGuardarDistribucion.disabled = !cuposValidos;
}

function pintarLeyendaFranjas(franjas) {
  if (!$leyendaFranjas) return;
  $leyendaFranjas.replaceChildren();
  franjas.forEach(franja => {
    const color = colorFranja(franja.hora_inicio, franja.rol);
    const item = el('span', 'inline-flex items-center gap-1');
    const muestra = el('span', 'inline-block w-3 h-3 rounded');
    muestra.style.backgroundColor = color;
    item.append(
      muestra,
      document.createTextNode(
        `${franja.rol} · ${franja.nombre} (${franja.hora_inicio})`
      ),
    );
    $leyendaFranjas.appendChild(item);
  });
}


// =====================================================================
// BLOQUE C: Mensajes en pantalla
// =====================================================================
function limpiarAvisos() {
  $avisos.replaceChildren();
}

function mostrarAvisos(lista) {
  limpiarAvisos();
  if (!lista || lista.length === 0) {
    $avisos.appendChild(el('p',
      'text-green-800 bg-green-100 rounded px-3 py-2 text-sm',
      'Todas las franjas están cubiertas esta semana.'));
    return;
  }
  lista.forEach(texto => {
    $avisos.appendChild(el('p',
      'text-amber-800 bg-amber-100 rounded px-3 py-1 mb-1 text-sm',
      '⚠ ' + texto));
  });
}

function mostrarOk(texto) {
  limpiarAvisos();
  $avisos.appendChild(el('p', 'text-green-800 bg-green-100 rounded px-3 py-2 text-sm', texto));
}

function mostrarError(texto) {
  limpiarAvisos();
  $avisos.appendChild(el('p',
    'text-red-800 bg-red-100 rounded px-3 py-2 text-sm', texto));
}

function tablaDescansos(rol, filas, resumen) {
  const seccion = el('div', 'mb-5 last:mb-0');
  const promedio = resumen?.promedio_descansos_fin_semana ?? 0;
  const promedioCompletos = resumen?.promedio_fines_semana_completos ?? 0;
  const promedioFestivos = resumen?.promedio_festivos_descanso ?? 0;
  const promedioFestivosTrabajados = resumen?.promedio_festivos_trabajados ?? 0;
  seccion.appendChild(el(
    'h3',
    'font-semibold mb-1',
    `${rol} · promedio ${promedio} día(s) de descanso en fin de semana, ${promedioCompletos} fin(es) de semana completo(s), ${promedioFestivosTrabajados} festivo(s) trabajado(s) y ${promedioFestivos} festivo(s) descansado(s) por persona`,
  ));
  const contenedor = el('div', 'overflow-x-auto');
  const tabla = el('table', 'min-w-full text-sm border-collapse');
  const filaTitulo = el('tr', 'bg-slate-100 text-left');
  [
    'Empleado',
    'Descansos totales',
    'Sábados',
    'Domingos',
    'Festivos trabajados',
    'Festivos descansados',
    'Días fin de semana',
    'Fines de semana completos',
    'Fines de semana registrados',
  ].forEach(texto => filaTitulo.appendChild(
    el('th', 'p-2 border-b border-slate-200 whitespace-nowrap', texto)
  ));
  const cabeza = el('thead');
  cabeza.appendChild(filaTitulo);
  tabla.appendChild(cabeza);

  const cuerpo = el('tbody');
  filas.forEach(fila => {
    const tr = el('tr', 'border-b border-slate-100');
    tr.appendChild(el('td', 'p-2 font-medium', fila.nombre));
    [
      fila.total_descansos,
      fila.sabados_descanso,
      fila.domingos_descanso,
    ].forEach(valor => tr.appendChild(
      el('td', 'p-2 text-center tabular-nums', String(valor))
    ));
    const festivos = fila.festivos_descanso || [];
    const formatearFechas = fechas => fechas.map(fecha =>
      `${fecha.slice(8, 10)}/${fecha.slice(5, 7)}/${fecha.slice(0, 4)}`
    ).join(', ');
    const festivosTrabajados = fila.festivos_trabajados || [];
    tr.appendChild(el(
      'td',
      'p-2 text-center',
      festivosTrabajados.length
        ? `${fila.total_festivos_trabajados}: ${formatearFechas(festivosTrabajados)}`
        : '0',
    ));
    tr.appendChild(el(
      'td',
      'p-2 text-center',
      festivos.length
        ? `${fila.total_festivos_descanso}: ${formatearFechas(festivos)}`
        : '0',
    ));
    [
      fila.dias_descanso_fin_semana,
      fila.fines_semana_completos,
      fila.fines_semana_observados,
    ].forEach(valor => tr.appendChild(
      el('td', 'p-2 text-center tabular-nums', String(valor))
    ));
    cuerpo.appendChild(tr);
  });
  tabla.appendChild(cuerpo);
  contenedor.appendChild(tabla);
  seccion.appendChild(contenedor);
  return seccion;
}

async function cargarDashboardDescansos() {
  try {
    const respuesta = await fetch('/api/dashboard/descansos/', {
      cache: 'no-store',
    });
    const datos = await respuesta.json();
    if (!respuesta.ok) {
      throw new Error(datos.error || `El servidor respondió ${respuesta.status}`);
    }
    $dashboardDescansos.replaceChildren();
    if (!datos.fecha_inicio || !datos.fecha_fin) {
      $dashboardPeriodo.textContent = '';
      $dashboardDescansos.appendChild(el(
        'p',
        'text-sm text-slate-500',
        'Aún no hay descansos generados para técnicos o supervisores.',
      ));
      return;
    }
    $dashboardPeriodo.textContent =
      `Periodo registrado: ${datos.fecha_inicio} a ${datos.fecha_fin}`;
    const roles = Object.keys(datos.grupos);
    if (!roles.length) {
      $dashboardDescansos.appendChild(el(
        'p',
        'text-sm text-slate-500',
        'No hay técnicos ni supervisores activos.',
      ));
      return;
    }
    roles.forEach(rol => {
      $dashboardDescansos.appendChild(
        tablaDescansos(rol, datos.grupos[rol], datos.resumen[rol])
      );
    });
    $dashboardDescansos.appendChild(el(
      'p',
      'text-xs text-slate-500 mt-2',
      'Se muestran las fechas de los festivos trabajados y descansados, sin incluir el motivo del festivo.',
    ));
  } catch (error) {
    $dashboardDescansos.replaceChildren(el(
      'p',
      'text-red-700 bg-red-50 rounded p-3 text-sm',
      `No se pudo cargar el dashboard de descansos: ${error.message}`,
    ));
  }
}

async function cargarAsignacionActa() {
  const fechaMes = `${fechaActual.slice(0, 7)}-01`;
  const fechaMesDate = desdeTexto(fechaMes);
  $actaMes.textContent = new Intl.DateTimeFormat('es-CO', {
    month: 'long',
    year: 'numeric',
  }).format(fechaMesDate);
  $actaAsignado.textContent = 'Cargando asignación…';
  $actaMensaje.textContent = '';
  try {
    const respuesta = await fetch(
      `/api/acta-retribucion/?fecha=${fechaMes}`,
      { cache: 'no-store' },
    );
    const tipoContenido = respuesta.headers.get('content-type') || '';
    if (!tipoContenido.includes('application/json')) {
      throw new Error(
        `El servidor respondió ${respuesta.status} con una página HTML. ` +
        'Verifica que las migraciones de Django estén aplicadas.',
      );
    }
    const datos = await respuesta.json();
    if (!respuesta.ok) {
      throw new Error(datos.error || `El servidor respondió ${respuesta.status}`);
    }

    $actaSupervisor.replaceChildren(...datos.supervisores.map(supervisor => {
      const opcion = el('option', '', supervisor.nombre);
      opcion.value = String(supervisor.id);
      return opcion;
    }));
    $actaControles.classList.toggle(
      'hidden',
      !ES_ADMIN || datos.supervisores.length === 0,
    );
    if (!datos.asignacion) {
      $actaAsignado.textContent = 'No hay supervisores activos para asignar.';
      return;
    }
    $actaAsignado.textContent =
      `Responsable asignado: ${datos.asignacion.supervisor}`;
    $actaSupervisor.value = String(datos.asignacion.supervisor_id);
  } catch (error) {
    $actaAsignado.textContent = 'No se pudo cargar la asignación.';
    $actaMensaje.className = 'text-sm mt-2 text-red-700';
    $actaMensaje.textContent = error.message;
  }
}

$actaGuardar.addEventListener('click', async () => {
  $actaGuardar.disabled = true;
  $actaMensaje.className = 'text-sm mt-2';
  $actaMensaje.textContent = '';
  try {
    const fechaMes = `${fechaActual.slice(0, 7)}-01`;
    const resultado = await enviarJSON('/api/acta-retribucion/reasignar/', {
      fecha: fechaMes,
      supervisor_id: Number($actaSupervisor.value),
    });
    if (!resultado.ok) {
      throw new Error(
        resultado.datos.error || `El servidor respondió ${resultado.estado}`,
      );
    }
    $actaAsignado.textContent =
      `Responsable asignado: ${resultado.datos.asignacion.supervisor}`;
    $actaMensaje.className = 'text-sm mt-2 text-green-700';
    $actaMensaje.textContent = 'Asignación guardada.';
  } catch (error) {
    $actaMensaje.className = 'text-sm mt-2 text-red-700';
    $actaMensaje.textContent = error.message;
  } finally {
    $actaGuardar.disabled = false;
  }
});


// =====================================================================
// BLOQUE D: Dibujar la tabla
// =====================================================================
function celdaTurno(turno, esHoy, emp, dia) {
  const festivo = datosSemana?.festivos?.find(item => item.fecha === dia);
  let clases = 'p-2 text-center border-l border-slate-100';
  if (festivo) clases += ' bg-amber-50';
  if (esHoy) clases += ' ring-2 ring-inset ring-indigo-400';
  const tieneHorario = turno && turno.inicio && turno.fin;
  const editable = ES_ADMIN && turno && !turno.novedad && (turno.descanso || tieneHorario);
  if (editable) clases += ' cursor-pointer';
  const td = el('td', clases);
  if (tieneHorario && !turno.novedad && !turno.descanso) {
    const franja = datosSemana.franjas.find(
      item => item.id === turno.franja_id
    );
    const color = colorFranja(
      franja?.hora_inicio || turno.inicio,
      franja?.rol || emp.rol,
    );
    const horaInicio = franja?.hora_inicio || turno.inicio;
    td.style.backgroundColor = color || '#f1f5f9';
    const turnoOscuro = horaInicio === '23:00';
    if (turnoOscuro) td.style.color = '#ffffff';
    td.title = franja
      ? `${franja.rol} · ${franja.nombre} (${franja.hora_inicio})`
      : `Turno ${turno.inicio}–${turno.fin}`;
    if (festivo) td.classList.add('border-t-2', 'border-t-amber-500');
  }

  if (!turno) {
    td.appendChild(el('span', 'text-slate-300', '—'));
  } else if (turno.novedad) {
    const info = NOVEDADES[turno.novedad] || { texto: turno.novedad, clases: 'bg-slate-200 text-slate-800' };
    td.appendChild(el('span',
      'inline-block px-2 py-1 rounded text-xs font-semibold ' + info.clases, info.texto));
  } else if (turno.descanso) {
    td.appendChild(el('span',
      'inline-block px-2 py-1 rounded bg-amber-200 text-amber-900 text-xs font-semibold',
      'Descanso'));
  } else if (!tieneHorario) {
    td.appendChild(el('span', 'text-slate-300', '—'));
  } else {
    const cruza = turno.fin < turno.inicio;   // ej. 23:00 -> 06:00
    td.appendChild(el('div', 'font-semibold', turno.inicio));
    const horaInicio = datosSemana.franjas.find(
      item => item.id === turno.franja_id
    )?.hora_inicio || turno.inicio;
    const clasesHoraFin = horaInicio === '23:00'
      ? 'text-xs text-white'
      : 'text-xs text-slate-500';
    td.appendChild(el('div', clasesHoraFin, turno.fin + (cruza ? ' (+1)' : '')));
    if (turno.remoto) {
      td.appendChild(el(
        'div',
        horaInicio === '23:00'
          ? 'text-xs font-semibold text-white'
          : 'text-xs font-semibold text-sky-700',
        'DS',
      ));
    }
  }

  if (turno && turno.manual) {
    const marca = el('div', 'text-xs text-indigo-600', '✎');
    marca.title = 'Ajustado a mano';
    td.appendChild(marca);
  }
  if (editable) td.addEventListener('click', () => abrirEdicion(emp, dia));
  return td;
}

function pintar(datos) {
  datosSemana = datos;
  pintarDistribucionTecnicos(datos.distribucion_tecnicos);
  pintarLeyendaFranjas(datos.franjas || []);
  const hoy = aTexto(new Date());

  // Rango de fechas arriba de la tabla
  const primero = desdeTexto(datos.dias[0]);
  const ultimo = desdeTexto(datos.dias[6]);
  $rango.textContent =
    `${primero.getDate()} ${MESES[primero.getMonth()]} – ` +
    `${ultimo.getDate()} ${MESES[ultimo.getMonth()]} ${ultimo.getFullYear()}`;

  // Aviso si la semana no tiene turnos generados
  $info.replaceChildren();
  const hayTurnos = datos.empleados.some(e =>
    Object.values(e.turnos).some(turnoGenerado)
  );
  if (!hayTurnos) {
    $info.appendChild(el('p',
      'text-sky-800 bg-sky-100 rounded px-3 py-2 text-sm',
      ES_ADMIN
        ? 'Esta semana todavía no tiene turnos. Presiona «Generar turnos de esta semana».'
        : 'Esta semana todavía no tiene turnos generados.'));
  }

  $tabla.replaceChildren();

  // --- Encabezado ---
  const thead = el('thead', 'bg-slate-800 text-white');
  const filaHead = el('tr');
  filaHead.appendChild(el('th', 'p-3 text-left sticky left-0 bg-slate-800', 'Empleado'));
  datos.dias.forEach((d, i) => {
    const f = desdeTexto(d);
    const festivo = datos.festivos?.find(item => item.fecha === d);
    let clases = 'p-2 font-semibold';
    if (festivo) clases += ' bg-amber-700';
    if (d === hoy) clases += ' bg-indigo-600';
    const th = el('th', clases);
    if (festivo) th.title = `Festivo: ${festivo.nombre}`;
    th.appendChild(el('div', '', DIAS[i]));
    th.appendChild(el('div', 'text-xs font-normal opacity-80',
      `${f.getDate()} ${MESES[f.getMonth()]}`));
    if (festivo) {
      th.appendChild(el(
        'div',
        'mt-1 text-[10px] leading-tight font-medium',
        `Festivo · ${festivo.nombre}`
      ));
    }
    filaHead.appendChild(th);
  });
  filaHead.appendChild(el('th', 'p-3', 'Horas'));
  thead.appendChild(filaHead);
  $tabla.appendChild(thead);

  // --- Cuerpo ---
  const tbody = el('tbody');
  if (datos.empleados.length === 0) {
    const fila = el('tr');
    const td = el('td', 'p-6 text-center text-slate-500',
      'No hay empleados activos. Créalos en «Personal y horarios».');
    td.colSpan = 9;
    fila.appendChild(td);
    tbody.appendChild(fila);
  }

  let rolActual = null;
  datos.empleados.forEach(e => {
    // Fila separadora cada vez que cambia el rol
    if (e.rol !== rolActual) {
      rolActual = e.rol;
      const sep = el('tr');
      const td = el('td', 'bg-slate-200 text-slate-700 font-bold text-xs tracking-wide px-3 py-1',
        e.rol.toUpperCase());
      td.colSpan = 9;
      sep.appendChild(td);
      tbody.appendChild(sep);
    }

    const fila = el('tr', 'border-b border-slate-100');

    // Columna del nombre (queda fija al hacer scroll)
    const tdNombre = el('td', 'p-3 sticky left-0 bg-white');
    tdNombre.appendChild(el('div', 'font-medium', e.nombre));
    tdNombre.appendChild(el('div', 'text-xs text-slate-500', e.franja || 'Sin franja'));
    fila.appendChild(tdNombre);

    // Una celda por día
    datos.dias.forEach(d => {
      fila.appendChild(celdaTurno(e.turnos[d], d === hoy, e, d));
    });

    // Horas de la semana contra la meta del rol
    const meta = e.horas_meta;
    const tdHoras = el('td', 'p-2 text-center font-bold');
    const turnosGenerados = Object.values(e.turnos).some(turnoGenerado);
    if (!turnosGenerados) {
      tdHoras.textContent = '—';
      tdHoras.classList.add('text-slate-300');
    } else {
      tdHoras.textContent = `${e.horas_semana} h`;
      tdHoras.classList.add(e.horas_semana === meta ? 'text-green-700' : 'text-red-700');
    }
    fila.appendChild(tdHoras);

    tbody.appendChild(fila);
  });
  $tabla.appendChild(tbody);
}


// =====================================================================
// BLOQUE E: Pedir datos y navegar entre semanas
// =====================================================================
async function cargar() {
  try {
    const respuesta = await fetch(`/api/semana/?fecha=${fechaActual}`);
    if (!respuesta.ok) throw new Error('El servidor respondió ' + respuesta.status);
    pintar(await respuesta.json());
  } catch (error) {
    mostrarError('No se pudieron cargar los turnos: ' + error.message);
  }
}

function irA(texto) {
  fechaActual = texto;
  limpiarAvisos();
  cargar();
  cargarAsignacionActa();
}

document.getElementById('btn-anterior').addEventListener('click', () => irA(sumarDias(fechaActual, -7)));
document.getElementById('btn-siguiente').addEventListener('click', () => irA(sumarDias(fechaActual, 7)));
document.getElementById('btn-hoy').addEventListener('click', () => irA(aTexto(new Date())));
$btnCopiarImagen.addEventListener('click', copiarImagenHorario);
$btnExportarExcel.addEventListener('click', exportarExcelHorario);

if ($btnGuardarDistribucion) {
  $btnGuardarDistribucion.addEventListener('click', async () => {
    const distribucion = [...$distribucionTecnicos.querySelectorAll('input[data-franja-id]')]
      .map(input => ({
        franja_id: Number(input.dataset.franjaId),
        cantidad: Number(input.value),
      }));
    $btnGuardarDistribucion.disabled = true;
    const textoOriginal = $btnGuardarDistribucion.textContent;
    $btnGuardarDistribucion.textContent = 'Guardando…';
    try {
      const respuesta = await enviarJSON('/api/tecnicos/distribucion/', {
        fecha: fechaActual,
        distribucion,
      });
      if (!respuesta.ok) {
        throw new Error(respuesta.datos.error || `El servidor respondió ${respuesta.estado}`);
      }
      await cargar();
      mostrarOk(
        'Cupos guardados para esta semana. Pulsa «Generar turnos de esta semana» para aplicarlos.'
      );
    } catch (error) {
      mostrarError('No se pudieron guardar los cupos: ' + error.message);
      actualizarResumenDistribucion(datosSemana.distribucion_tecnicos.total);
    } finally {
      $btnGuardarDistribucion.textContent = textoOriginal;
    }
  });
}

// =====================================================================
// BLOQUE F: Generar turnos
// =====================================================================
async function generar(descartar = false) {
  const botones = [$btnGenerar, $btnDescartar];
  botones.forEach(b => { b.disabled = true; });
  const textoOriginal = $btnGenerar.textContent;
  $btnGenerar.textContent = 'Generando…';
  try {
    const respuesta = await fetch('/api/generar/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': leerCookie('csrftoken'),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: 'fecha=' + fechaActual + (descartar ? '&descartar=1' : ''),
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || 'El servidor respondió ' + respuesta.status);

    mostrarAvisos(datos.avisos);
    if (datos.manuales > 0) {
      $avisos.appendChild(el('p', 'text-sky-800 bg-sky-100 rounded px-3 py-2 text-sm mt-1',
        `Se respetaron los ajustes manuales de ${datos.manuales} persona(s) (marcados con ✎).`));
    }
    await cargar();
    await cargarDashboardDescansos();
  } catch (error) {
    mostrarError('No se pudieron generar los turnos: ' + error.message);
  } finally {
    botones.forEach(b => { b.disabled = false; });
    $btnGenerar.textContent = textoOriginal;
  }
}

$btnGenerar.addEventListener('click', () => generar(false));
$btnDescartar.addEventListener('click', () => {
  if (confirm('Se borrarán los ajustes manuales de esta semana y se recalculará todo. ¿Continuar?')) {
    generar(true);
  }
});

$btnLimpiar.addEventListener('click', async () => {
  if (!confirm(
    'Se dejarán en blanco todos los turnos de esta semana y se quitarán los ajustes manuales. ' +
    'Las incapacidades, vacaciones y permisos se conservarán. ¿Continuar?'
  )) {
    return;
  }

  const botones = [$btnGenerar, $btnDescartar, $btnLimpiar];
  botones.forEach(boton => { boton.disabled = true; });
  $btnLimpiar.textContent = 'Limpiando…';
  try {
    const respuesta = await fetch('/api/limpiar/', {
      method: 'POST',
      headers: {
        'X-CSRFToken': leerCookie('csrftoken'),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: 'fecha=' + fechaActual,
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) {
      throw new Error(datos.error || 'El servidor respondió ' + respuesta.status);
    }

    mostrarOk(`Se limpiaron ${datos.limpiados} casilla(s). Ya puedes generar los turnos de nuevo.`);
    await cargar();
    await cargarDashboardDescansos();
  } catch (error) {
    mostrarError('No se pudieron limpiar los turnos: ' + error.message);
  } finally {
    botones.forEach(boton => { boton.disabled = false; });
    $btnLimpiar.textContent = 'Limpiar semana';
  }
});


// =====================================================================
// BLOQUE G: Edición manual de turnos
// =====================================================================
const $dlg = document.getElementById('dlg-turno');
const $dtTitulo = document.getElementById('dt-titulo');
const $dtSub = document.getElementById('dt-sub');
const $dtMover = document.getElementById('dt-mover');
const $dtMoverTexto = document.getElementById('dt-mover-texto');
const $dtMoverDestinoLabel = document.getElementById('dt-mover-destino-label');
const $dtMoverDestino = document.getElementById('dt-mover-destino');
const $dtMoverBtn = document.getElementById('dt-mover-btn');
const $dtAgregarDescansoBtn = document.getElementById('dt-agregar-descanso-btn');
const $dtDescansoTrabajarBtn = document.getElementById('dt-descanso-trabajar-btn');
const $dtCambio = document.getElementById('dt-cambio');
const $dtCompanero = document.getElementById('dt-companero');
const $dtCambioBtn = document.getElementById('dt-cambio-btn');
const $dtFranjaTecnico = document.getElementById('dt-franja-tecnico');
const $dtFranjaSelect = document.getElementById('dt-franja-select');
const $dtFranjaBtn = document.getElementById('dt-franja-btn');
const $dtFinSemana = document.getElementById('dt-fin-semana');
const $dtSupervisorCompanero = document.getElementById('dt-supervisor-companero');
const $dtFinSemanaBtn = document.getElementById('dt-fin-semana-btn');
const $dtHorario = document.getElementById('dt-horario');
const $dtInicio = document.getElementById('dt-inicio');
const $dtHorarioBtn = document.getElementById('dt-horario-btn');
const $dtError = document.getElementById('dt-error');
const $dtForzar = document.getElementById('dt-forzar');
const $dtProblemas = document.getElementById('dt-problemas');
const $dtForzarBtn = document.getElementById('dt-forzar-btn');

let contexto = null;     // { emp, dia } de la casilla tocada
let reintentar = null;   // función que repite el cambio con forzar = true

function abrirEdicion(emp, dia) {
  const turno = emp.turnos[dia];
  const actual = diaDescanso(emp);
  contexto = { emp, dia };
  reintentar = null;
  $dtError.textContent = '';
  $dtForzar.classList.add('hidden');

  const f = desdeTexto(dia);
  $dtTitulo.textContent = emp.nombre;
  $dtSub.textContent =
    `${emp.rol} · ${emp.franja || 'Sin franja'} · ${nombreDia(dia)} ${f.getDate()} ${MESES[f.getMonth()]}`;

  // Opción 1: mover el descanso a este día (solo si hoy trabaja)
  const esSupervisor = emp.rol.toLowerCase() === 'supervisor';
  const esTecnico = emp.rol.normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').toLowerCase() === 'tecnico';
  const indiceDia = datosSemana.dias.indexOf(dia);
  const indiceCalendario = desdeTexto(dia).getDay();
  const esFinDeSemana =
    indiceDia === 5 || indiceDia === 6 || indiceCalendario === 0 || indiceCalendario === 6;
  const usaIntercambioFinSemana = esSupervisor && esFinDeSemana;
  const descansoEnCasilla = actual === dia;
  const diasAlternativos = Object.entries(emp.turnos)
    .filter(([fecha, estado]) =>
      fecha !== actual
      && !estado.descanso
      && (
        (!estado.novedad && Boolean(estado.inicio))
        || estado.novedad === 'PERMISO'
      )
    )
    .map(([fecha, estado]) => ({ fecha, reemplazaPermiso: estado.novedad === 'PERMISO' }));
  const puedeMover =
    !usaIntercambioFinSemana
    && actual !== null
    && (!turno.descanso || diasAlternativos.length > 0);
  const puedeAgregarDescanso =
    !usaIntercambioFinSemana
    && !turno.descanso
    && (!turno.novedad || turno.novedad === 'PERMISO');
  const puedeConvertirDescanso =
    !usaIntercambioFinSemana
    && Boolean(turno.descanso)
    && !turno.novedad;
  $dtMover.classList.toggle(
    'hidden',
    !puedeMover && !puedeAgregarDescanso && !puedeConvertirDescanso
  );
  $dtMoverBtn.classList.toggle('hidden', !puedeMover);
  $dtAgregarDescansoBtn.classList.toggle(
    'hidden',
    !puedeAgregarDescanso
  );
  $dtDescansoTrabajarBtn.classList.toggle(
    'hidden',
    !puedeConvertirDescanso
  );
  $dtMoverDestinoLabel.classList.toggle('hidden', !puedeMover || !descansoEnCasilla);
  $dtMoverDestino.classList.toggle('hidden', !puedeMover || !descansoEnCasilla);
  $dtAgregarDescansoBtn.textContent = turno.novedad === 'PERMISO'
    ? 'Reemplazar permiso por descanso adicional'
    : 'Agregar descanso sin mover el actual';
  if (puedeMover) {
    if (descansoEnCasilla) {
      $dtMoverTexto.textContent =
        `Este día es el descanso actual de ${emp.nombre}. Elige otro día laborable ` +
        `o un día de permiso; ${nombreDia(actual)} pasará a ser de trabajo. ` +
        'Si eliges un permiso, esa fecha se reemplazará por el descanso.';
      $dtMoverDestino.replaceChildren();
      diasAlternativos.forEach(({ fecha, reemplazaPermiso }) => {
        const fechaOpcion = desdeTexto(fecha);
        $dtMoverDestino.add(new Option(
          `${nombreDia(fecha)} ${fechaOpcion.getDate()} ${MESES[fechaOpcion.getMonth()]}` +
          (reemplazaPermiso
            ? ' · permiso se reemplazará por descanso'
            : ' · pasa a descanso'),
          fecha,
        ));
      });
      $dtMoverBtn.textContent = 'Cambiar día de descanso';
    } else {
      $dtMoverTexto.textContent =
        `Hoy descansa el ${nombreDia(actual)}. Ese día pasará a ser de trabajo ` +
        'y las horas de la semana no cambian.';
      $dtMoverBtn.textContent = 'Mover el descanso a este día';
    }
  }

  // Opción 2: intercambiar con un compañero del mismo rol (primero los que descansan este día)
  const companeros = datosSemana.empleados
    .filter(c => c.id !== emp.id && c.rol === emp.rol && diaDescanso(c))
    .sort((x, y) => (diaDescanso(y) === dia) - (diaDescanso(x) === dia));

  $dtCompanero.replaceChildren();
  companeros.forEach(c => {
    $dtCompanero.add(new Option(
      `${c.nombre} · ${c.franja || 'sin franja'} · descansa el ${nombreDia(diaDescanso(c))}`, c.id));
  });
  const hayCompaneros = companeros.length > 0 && actual !== null;
  $dtCambio.classList.toggle(
    'hidden',
    usaIntercambioFinSemana || !hayCompaneros
  );

  const estadoFinDeSemana = persona => {
    const sabado = persona.turnos[datosSemana.dias[5]];
    const domingo = persona.turnos[datosSemana.dias[6]];
    if (!sabado || !domingo) return null;
    return `${sabado.descanso ? 'R' : 'T'}${domingo.descanso ? 'R' : 'T'}`;
  };
  const patronActual = estadoFinDeSemana(emp);
  const supervisores = usaIntercambioFinSemana
    ? datosSemana.empleados.filter(persona =>
      persona.id !== emp.id
      && persona.rol.toLowerCase() === 'supervisor'
      && patronActual !== null
      && estadoFinDeSemana(persona) !== null
      && estadoFinDeSemana(persona) !== patronActual
    )
    : [];
  $dtSupervisorCompanero.replaceChildren();
  supervisores.forEach(persona => {
    const sabado = persona.turnos[datosSemana.dias[5]];
    const domingo = persona.turnos[datosSemana.dias[6]];
    const patron = sabado.descanso && domingo.descanso
      ? 'libre todo el fin de semana'
      : sabado.descanso
        ? 'trabaja domingo'
        : 'trabaja sábado';
    $dtSupervisorCompanero.add(new Option(`${persona.nombre} · ${patron}`, persona.id));
  });
  if (usaIntercambioFinSemana && !turno.descanso) {
    $dtFinSemana.querySelector('label').textContent =
      `Cambiar el turno del ${nombreDia(dia)} de ${emp.nombre}`;
  } else {
    $dtFinSemana.querySelector('label').textContent =
      'Cambiar el turno de fin de semana con otro supervisor';
  }
  $dtFinSemana.classList.toggle('hidden', !usaIntercambioFinSemana);

  const puedeEditarHorario =
    !usaIntercambioFinSemana
    && !turno.descanso
    && !turno.novedad
    && Boolean(turno.inicio);
  $dtHorario.classList.toggle('hidden', !puedeEditarHorario);
  $dtInicio.value = puedeEditarHorario ? turno.inicio : '';

  const franjasTecnico = esTecnico
    ? datosSemana.franjas.filter(franja => franja.rol === emp.rol)
    : [];
  $dtFranjaSelect.replaceChildren();
  franjasTecnico.forEach(franja => {
    $dtFranjaSelect.add(new Option(
      `${franja.nombre} · ${franja.hora_inicio}–${franja.hora_fin}`,
      franja.id,
      false,
      franja.nombre === emp.franja
    ));
  });
  $dtFranjaTecnico.classList.toggle(
    'hidden',
    !esTecnico || franjasTecnico.length < 2
  );

  if (
    !puedeMover && !puedeAgregarDescanso && !puedeConvertirDescanso
    && !hayCompaneros && !puedeEditarHorario
    && !(usaIntercambioFinSemana && supervisores.length > 0)
    && !(esTecnico && franjasTecnico.length > 1)
  ) {
    $dtError.textContent =
      turno.descanso && actual === dia && diasAlternativos.length === 0
        ? 'No hay otro día laborable disponible sin novedad para mover el descanso.'
        : usaIntercambioFinSemana
        ? 'No hay otro supervisor disponible con un patrón distinto para intercambiar.'
        : 'No hay cambios disponibles para esta casilla.';
  }
  $dlg.showModal();
}

async function ejecutarCambio(url, cuerpo) {
  $dtError.textContent = '';
  $dtForzar.classList.add('hidden');

  const r = await enviarJSON(url, cuerpo);
  if (r.ok) {
    $dlg.close();
    await cargar();
    await cargarDashboardDescansos();
    mostrarOk('Cambio aplicado. Quedó marcado con ✎ y el generador lo respetará.');
    return;
  }
  if (r.estado === 409 && r.datos.problemas) {
    $dtProblemas.replaceChildren(...r.datos.problemas.map(p => el('li', '', p)));
    $dtForzar.classList.remove('hidden');
    reintentar = () => ejecutarCambio(url, { ...cuerpo, forzar: true });
    return;
  }
  $dtError.textContent = r.datos.error || ('Error ' + r.estado);
}

$dtMoverBtn.addEventListener('click', () => {
  ejecutarCambio('/api/turnos/descanso/', {
    empleado_id: contexto.emp.id,
    fecha: contexto.emp.turnos[contexto.dia].descanso
      ? $dtMoverDestino.value
      : contexto.dia,
  });
});

$dtAgregarDescansoBtn.addEventListener('click', () => {
  ejecutarCambio('/api/turnos/descanso/agregar/', {
    empleado_id: contexto.emp.id,
    fecha: contexto.dia,
  });
});

$dtDescansoTrabajarBtn.addEventListener('click', () => {
  ejecutarCambio('/api/turnos/descanso/trabajar/', {
    empleado_id: contexto.emp.id,
    fecha: contexto.dia,
  });
});

$dtCambioBtn.addEventListener('click', () => {
  ejecutarCambio('/api/turnos/intercambiar/', {
    empleado_id: contexto.emp.id,
    companero_id: Number($dtCompanero.value),
    fecha: contexto.dia,
  });
});

$dtFranjaBtn.addEventListener('click', () => {
  ejecutarCambio('/api/tecnicos/franja/', {
    empleado_id: contexto.emp.id,
    fecha: contexto.dia,
    franja_id: Number($dtFranjaSelect.value),
  });
});

$dtFinSemanaBtn.addEventListener('click', () => {
  ejecutarCambio('/api/supervisores/fin-de-semana/intercambiar/', {
    empleado_id: contexto.emp.id,
    companero_id: Number($dtSupervisorCompanero.value),
    fecha: contexto.dia,
  });
});

$dtHorarioBtn.addEventListener('click', () => {
  if (!$dtInicio.value) {
    $dtError.textContent = 'Indica una hora de inicio válida.';
    return;
  }
  ejecutarCambio('/api/turnos/horario/', {
    empleado_id: contexto.emp.id,
    fecha: contexto.dia,
    inicio: $dtInicio.value,
  });
});

$dtForzarBtn.addEventListener('click', () => { if (reintentar) reintentar(); });
document.getElementById('dt-cerrar').addEventListener('click', () => $dlg.close());


// =====================================================================
// ARRANQUE
// =====================================================================
cargar();
cargarDashboardDescansos();
cargarAsignacionActa();