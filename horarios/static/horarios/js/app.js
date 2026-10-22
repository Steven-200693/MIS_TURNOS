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

const $tabla = document.getElementById('tabla');
const $rango = document.getElementById('rango');
const $info = document.getElementById('info');
const $avisos = document.getElementById('avisos');
const $btnGenerar = document.getElementById('btn-generar');
const $btnDescartar = document.getElementById('btn-descartar');
const $btnLimpiar = document.getElementById('btn-limpiar');
const $distribucionTecnicos = document.getElementById('distribucion-tecnicos');
const $distribucionResumen = document.getElementById('distribucion-resumen');
const $btnGuardarDistribucion = document.getElementById('btn-guardar-distribucion');

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


// =====================================================================
// BLOQUE D: Dibujar la tabla
// =====================================================================
function celdaTurno(turno, esHoy, emp, dia) {
  let clases = 'p-2 text-center border-l border-slate-100' + (esHoy ? ' bg-indigo-100' : '');
  const tieneHorario = turno && turno.inicio && turno.fin;
  const editable = ES_ADMIN && turno && !turno.novedad && (turno.descanso || tieneHorario);
  if (editable) clases += ' cursor-pointer hover:bg-slate-100';
  const td = el('td', clases);

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
    td.appendChild(el('div', 'text-xs text-slate-500', turno.fin + (cruza ? ' (+1)' : '')));
    if (turno.remoto) {
      td.appendChild(el('div', 'text-xs font-semibold text-sky-700', 'DS'));
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
    const th = el('th', 'p-2 font-semibold' + (d === hoy ? ' bg-indigo-600' : ''));
    th.appendChild(el('div', '', DIAS[i]));
    th.appendChild(el('div', 'text-xs font-normal opacity-80',
      `${f.getDate()} ${MESES[f.getMonth()]}`));
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
}

document.getElementById('btn-anterior').addEventListener('click', () => irA(sumarDias(fechaActual, -7)));
document.getElementById('btn-siguiente').addEventListener('click', () => irA(sumarDias(fechaActual, 7)));
document.getElementById('btn-hoy').addEventListener('click', () => irA(aTexto(new Date())));

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
const $dtMoverBtn = document.getElementById('dt-mover-btn');
const $dtCambio = document.getElementById('dt-cambio');
const $dtCompanero = document.getElementById('dt-companero');
const $dtCambioBtn = document.getElementById('dt-cambio-btn');
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
  const puedeMover = !turno.descanso && actual !== null;
  $dtMover.classList.toggle('hidden', !puedeMover);
  if (puedeMover) {
    $dtMoverTexto.textContent =
      `Hoy descansa el ${nombreDia(actual)}. Ese día pasará a ser de trabajo ` +
      `y las horas de la semana no cambian.`;
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
  $dtCambio.classList.toggle('hidden', !hayCompaneros);

  const puedeEditarHorario = !turno.descanso && !turno.novedad && Boolean(turno.inicio);
  $dtHorario.classList.toggle('hidden', !puedeEditarHorario);
  $dtInicio.value = puedeEditarHorario ? turno.inicio : '';

  if (!puedeMover && !hayCompaneros && !puedeEditarHorario) {
    $dtError.textContent =
      'No hay cambios disponibles para esta casilla.';
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