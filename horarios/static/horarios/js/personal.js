const $mensaje = document.getElementById('mensaje');
const $empleados = document.getElementById('tabla-empleados');
const $franjas = document.getElementById('tabla-franjas');
const $roles = document.getElementById('tabla-roles');

const $dialogo = document.getElementById('dialogo');
const $formulario = document.getElementById('formulario');
const $titulo = document.getElementById('dialogo-titulo');
const $campos = document.getElementById('dialogo-campos');
const $errorForm = document.getElementById('dialogo-error');
const $novedades = document.getElementById('tabla-novedades');

const CLASE_CONTROL = 'w-full border border-slate-300 rounded px-3 py-2 bg-white';

const PREFERENCIAS = [
  { valor: 'CUALQUIERA', texto: 'Cualquier día' },
  { valor: 'SEMANA', texto: 'Entre semana (lun-vie)' },
  { valor: 'FINDE', texto: 'Fin de semana (sáb-dom)' },
];

// Copia local de lo que devuelve /api/personal/
let datos = { roles: [], franjas: [], empleados: [], novedades: [], tipos_novedad: [] };

function el(etiqueta, clases = '', texto = '') {
  const nodo = document.createElement(etiqueta);
  if (clases) nodo.className = clases;
  if (texto !== '') nodo.textContent = texto;
  return nodo;
}

function boton(texto, clases, alClic) {
  const b = el('button', 'px-2 py-1 rounded text-xs font-semibold ' + clases, texto);
  b.type = 'button';
  b.addEventListener('click', alClic);
  return b;
}

function leerCookie(nombre) {
  const par = document.cookie.split('; ').find(c => c.startsWith(nombre + '='));
  return par ? par.split('=')[1] : null;
}

function etiquetaPreferencia(valor) {
  const p = PREFERENCIAS.find(x => x.valor === valor);
  return p ? p.texto : valor;
}

// Envía datos en JSON al servidor. Si algo falla, lanza un Error con el mensaje.
async function enviar(url, cuerpo) {
  const respuesta = await fetch(url, {
    method: 'POST',
    headers: {
      'X-CSRFToken': leerCookie('csrftoken'),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(cuerpo),
  });
  const resultado = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(resultado.error || 'Error ' + respuesta.status);
  return resultado;
}

let temporizador;
function mostrarMensaje(texto, tipo = 'ok') {
  const colores = tipo === 'ok' ? 'text-green-800 bg-green-100' : 'text-red-800 bg-red-100';
  $mensaje.replaceChildren(el('p', colores + ' rounded px-3 py-2 text-sm', texto));
  clearTimeout(temporizador);
    temporizador = setTimeout(() => $mensaje.replaceChildren(), tipo === 'ok' ? 6000 : 15000);
}

// Dibuja una tabla genérica. Cada fila: { celdas: [texto o elemento], inactiva: true/false }
function dibujarTabla($tabla, encabezados, filas, textoVacio) {
  $tabla.replaceChildren();

  const thead = el('thead', 'bg-slate-800 text-white');
  const filaHead = el('tr');
  encabezados.forEach(t => filaHead.appendChild(el('th', 'p-3 text-left', t)));
  thead.appendChild(filaHead);
  $tabla.appendChild(thead);

  const tbody = el('tbody');
  if (filas.length === 0) {
    const tr = el('tr');
    const td = el('td', 'p-4 text-center text-slate-500', textoVacio);
    td.colSpan = encabezados.length;
    tr.appendChild(td);
    tbody.appendChild(tr);
  }
  filas.forEach(fila => {
    const tr = el('tr', 'border-b border-slate-100' + (fila.inactiva ? ' opacity-50' : ''));
    fila.celdas.forEach(celda => {
      const td = el('td', 'p-3');
      if (celda instanceof Node) td.appendChild(celda);
      else td.textContent = celda;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  $tabla.appendChild(tbody);
}

function pintarRoles() {
  const filas = datos.roles.map(r => {
    const acciones = el('div', 'flex gap-1');
    acciones.appendChild(boton('Editar', 'bg-slate-200 hover:bg-slate-300', () => formRol(r)));
    return { celdas: [r.nombre, r.horas_por_dia + ' h', r.horas_semana + ' h', acciones] };
  });
  dibujarTabla($roles, ['Rol', 'Horas por día', 'Horas por semana', 'Acciones'],
    filas, 'Todavía no hay roles. Crea el primero.');
}

function pintarFranjas() {
  const filas = datos.franjas.map(f => {
    // Cada persona descansa 1 de 7 días: para tener "m" personas cada día hacen falta m + ceil(m/6)
    const necesarios = f.minimo_personas + Math.ceil(f.minimo_personas / 6);
    const completo = f.activos >= necesarios;
    const estado = el('span', 'font-semibold ' + (completo ? 'text-green-700' : 'text-red-700'),
      `${f.activos} / ${necesarios}`);

    const acciones = el('div', 'flex gap-1');
    acciones.appendChild(boton('Editar', 'bg-slate-200 hover:bg-slate-300', () => formFranja(f)));
    acciones.appendChild(boton('Eliminar', 'bg-red-100 hover:bg-red-200 text-red-800', () => eliminarFranja(f)));

    return { celdas: [f.rol, f.nombre, `${f.hora_inicio} – ${f.hora_fin}`,
                      f.minimo_personas, estado, acciones] };
  });
  dibujarTabla($franjas,
    ['Rol', 'Franja', 'Horario', 'Mínimo por día', 'Activos / necesarios', 'Acciones'],
    filas, 'Todavía no hay franjas.');
}

function pintarEmpleados() {
  const filas = datos.empleados.map(e => {
    const estado = el('span',
      'px-2 py-1 rounded text-xs font-semibold ' +
      (e.activo ? 'bg-green-100 text-green-800' : 'bg-slate-200 text-slate-600'),
      e.activo ? 'Activo' : 'Inactivo');

    const acciones = el('div', 'flex gap-1');
    acciones.appendChild(boton('Editar', 'bg-slate-200 hover:bg-slate-300', () => formEmpleado(e)));
    acciones.appendChild(e.activo
      ? boton('Desactivar', 'bg-amber-200 hover:bg-amber-300 text-amber-900', () => cambiarActivo(e, false))
      : boton('Activar', 'bg-green-200 hover:bg-green-300 text-green-900', () => cambiarActivo(e, true)));

    return {
      inactiva: !e.activo,
      celdas: [e.nombre, e.rol, e.franja || 'Sin franja',
               etiquetaPreferencia(e.preferencia_descanso), estado, acciones],
    };
  });
  dibujarTabla($empleados,
    ['Nombre', 'Rol', 'Franja', 'Descanso preferido', 'Estado', 'Acciones'],
    filas, 'Todavía no hay empleados.');
}

function llenarSelect(select, opciones, seleccionado) {
  select.replaceChildren();
  opciones.forEach(o => select.add(new Option(o.texto, o.valor)));
  select.value = seleccionado ?? '';
  if (select.selectedIndex === -1) select.selectedIndex = 0;
}

// Arma el formulario a partir de una lista de campos y lo muestra.
// Devuelve los controles para que quien llama pueda engancharles eventos.
function abrirFormulario(titulo, campos, valores, alGuardar) {
  $titulo.textContent = titulo;
  $errorForm.textContent = '';
  $campos.replaceChildren();
  const controles = {};

  campos.forEach(c => {
    const etiqueta = el('label', 'block mb-3');
    etiqueta.appendChild(el('span', 'block text-sm font-medium mb-1', c.etiqueta));

    let control;
    if (c.tipo === 'select') {
      control = el('select', CLASE_CONTROL);
      llenarSelect(control, c.opciones, valores[c.nombre]);
    } else {
      control = el('input', CLASE_CONTROL);
      control.type = c.tipo;                       // text, number o time
      control.value = valores[c.nombre] ?? '';
      if (c.min !== undefined) control.min = c.min;
      if (c.max !== undefined) control.max = c.max;
      control.required = !c.opcional;
    }
    etiqueta.appendChild(control);
    $campos.appendChild(etiqueta);
    controles[c.nombre] = control;
  });

  $formulario.onsubmit = async (evento) => {
    evento.preventDefault();
    const cuerpo = {};
    if (valores.id) cuerpo.id = valores.id;
    campos.forEach(c => {
      let v = controles[c.nombre].value;
      if (c.tipo === 'number') v = Number(v);
      if (c.numerico) v = (v === '' ? null : Number(v));
      cuerpo[c.nombre] = v;
    });
    try {
      await alGuardar(cuerpo);
      $dialogo.close();
    } catch (error) {
      $errorForm.textContent = error.message;   // el error se muestra dentro de la ventana
    }
  };

  $dialogo.showModal();
  return controles;
}

document.getElementById('dialogo-cancelar').addEventListener('click', () => $dialogo.close());

function formRol(rol = {}) {
  abrirFormulario(rol.id ? 'Editar rol' : 'Nuevo rol', [
    { nombre: 'nombre', etiqueta: 'Nombre del rol', tipo: 'text' },
    { nombre: 'horas_por_dia', etiqueta: 'Horas por día (1 a 12)', tipo: 'number', min: 1, max: 12 },
  ], rol, async (cuerpo) => {
    await enviar('/api/roles/guardar/', cuerpo);
    await cargar();
    mostrarMensaje('Rol guardado. Si cambiaste las horas, vuelve a generar los turnos de las semanas afectadas.');
  });
}

function formFranja(franja = {}) {
  if (datos.roles.length === 0) {
    mostrarMensaje('Primero crea al menos un rol.', 'error');
    return;
  }
  abrirFormulario(franja.id ? 'Editar franja' : 'Nueva franja', [
    { nombre: 'rol_id', etiqueta: 'Rol', tipo: 'select', numerico: true,
      opciones: datos.roles.map(r => ({ valor: r.id, texto: r.nombre })) },
    { nombre: 'nombre', etiqueta: 'Nombre de la franja (ej. Mañana)', tipo: 'text' },
    { nombre: 'hora_inicio', etiqueta: 'Hora de entrada', tipo: 'time' },
    { nombre: 'minimo_personas', etiqueta: 'Mínimo de personas por día', tipo: 'number', min: 0, max: 50 },
  ], { minimo_personas: 1, ...franja }, async (cuerpo) => {
    await enviar('/api/franjas/guardar/', cuerpo);
    await cargar();
    mostrarMensaje('Franja guardada. Vuelve a generar los turnos para aplicar el cambio.');
  });
}

function formEmpleado(empleado = {}) {
  if (datos.roles.length === 0) {
    mostrarMensaje('Primero crea al menos un rol.', 'error');
    return;
  }
  const controles = abrirFormulario(empleado.id ? 'Editar empleado' : 'Nuevo empleado', [
    { nombre: 'nombre', etiqueta: 'Nombre completo', tipo: 'text' },
    { nombre: 'rol_id', etiqueta: 'Rol', tipo: 'select', numerico: true,
      opciones: datos.roles.map(r => ({ valor: r.id, texto: r.nombre })) },
    { nombre: 'franja_id', etiqueta: 'Franja', tipo: 'select', numerico: true,
      opciones: [{ valor: '', texto: 'Sin franja' }] },
    { nombre: 'preferencia_descanso', etiqueta: 'Día de descanso preferido', tipo: 'select',
      opciones: PREFERENCIAS },
  ], empleado, async (cuerpo) => {
    await enviar('/api/empleados/guardar/', cuerpo);
    await cargar();
    mostrarMensaje('Empleado guardado. Genera los turnos para incluirlo en el horario.');
  });

  // La lista de franjas depende del rol elegido
  const opcionesFranja = (rolId) => [{ valor: '', texto: 'Sin franja' }].concat(
    datos.franjas
      .filter(f => f.rol_id === Number(rolId))
      .map(f => ({ valor: f.id, texto: `${f.nombre} (${f.hora_inicio}–${f.hora_fin})` }))
  );
  const refrescarFranjas = (seleccion) =>
    llenarSelect(controles.franja_id, opcionesFranja(controles.rol_id.value), seleccion);

  refrescarFranjas(empleado.franja_id);
  controles.rol_id.addEventListener('change', () => refrescarFranjas(''));
}

async function cambiarActivo(empleado, activo) {
  const pregunta = activo
    ? `¿Reactivar a ${empleado.nombre}?`
    : `¿Desactivar a ${empleado.nombre}?\nSus turnos pasados se conservan y no se le generarán turnos nuevos.`;
  if (!confirm(pregunta)) return;
  try {
    await enviar('/api/empleados/guardar/', { id: empleado.id, activo });
    await cargar();
    mostrarMensaje(activo ? 'Empleado reactivado.' : 'Empleado desactivado.');
  } catch (error) {
    mostrarMensaje(error.message, 'error');
  }
}

async function eliminarFranja(franja) {
  if (!confirm(`¿Eliminar la franja «${franja.rol} · ${franja.nombre}»?`)) return;
  try {
    await enviar('/api/franjas/eliminar/', { id: franja.id });
    await cargar();
    mostrarMensaje('Franja eliminada.');
  } catch (error) {
    mostrarMensaje(error.message, 'error');
  }
}

function pintarNovedades() {
  const filas = datos.novedades.map(n => {
    const acciones = el('div', 'flex gap-1');
    acciones.appendChild(boton('Editar', 'bg-slate-200 hover:bg-slate-300', () => formNovedad(n)));
    acciones.appendChild(boton('Eliminar', 'bg-red-100 hover:bg-red-200 text-red-800', () => eliminarNovedad(n)));
    const rango = n.fecha_inicio === n.fecha_fin
      ? n.fecha_inicio : `${n.fecha_inicio} → ${n.fecha_fin}`;
    return { celdas: [n.empleado, n.tipo_texto, rango, n.nota || '—', acciones] };
  });
  dibujarTabla($novedades, ['Empleado', 'Tipo', 'Fechas', 'Nota', 'Acciones'],
    filas, 'No hay novedades registradas.');
}

function resultadoNovedad(r, accion) {
  let texto = accion + (r.semanas > 0
    ? ` Se recalcularon ${r.semanas} semana(s) ya generadas.`
    : ' Aún no hay semanas generadas en esas fechas: se aplicará cuando las generes.');
  if (r.avisos && r.avisos.length > 0) {
    mostrarMensaje(texto + ' Atención: ' + r.avisos.join(' | '), 'error');
  } else {
    mostrarMensaje(texto);
  }
}

function formNovedad(nov = {}) {
  const empleados = datos.empleados.filter(e => e.activo || e.id === nov.empleado_id);
  if (empleados.length === 0) {
    mostrarMensaje('Primero crea al menos un empleado.', 'error');
    return;
  }
  abrirFormulario(nov.id ? 'Editar novedad' : 'Nueva novedad', [
    { nombre: 'empleado_id', etiqueta: 'Empleado', tipo: 'select', numerico: true,
      opciones: empleados.map(e => ({ valor: e.id, texto: `${e.nombre} (${e.rol})` })) },
    { nombre: 'tipo', etiqueta: 'Tipo de novedad', tipo: 'select',
      opciones: datos.tipos_novedad },
    { nombre: 'fecha_inicio', etiqueta: 'Desde', tipo: 'date' },
    { nombre: 'fecha_fin', etiqueta: 'Hasta (inclusive)', tipo: 'date' },
    { nombre: 'nota', etiqueta: 'Nota (opcional)', tipo: 'text', opcional: true },
  ], nov, async (cuerpo) => {
    const r = await enviar('/api/novedades/guardar/', cuerpo);
    await cargar();
    resultadoNovedad(r, 'Novedad guardada.');
  });
}

async function eliminarNovedad(nov) {
  if (!confirm(`¿Eliminar la novedad de ${nov.empleado} (${nov.tipo_texto})?`)) return;
  try {
    const r = await enviar('/api/novedades/eliminar/', { id: nov.id });
    await cargar();
    resultadoNovedad(r, 'Novedad eliminada.');
  } catch (error) {
    mostrarMensaje(error.message, 'error');
  }
}



async function cargar() {
  try {
    const respuesta = await fetch('/api/personal/');
    const resultado = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(resultado.error || 'Error ' + respuesta.status);
    datos = resultado;
    pintarRoles();
    pintarFranjas();
    pintarEmpleados();
    pintarNovedades();
  } catch (error) {
    mostrarMensaje('No se pudieron cargar los datos: ' + error.message, 'error');
  }
}

document.getElementById('btn-nuevo-empleado').addEventListener('click', () => formEmpleado());
document.getElementById('btn-nueva-franja').addEventListener('click', () => formFranja());
document.getElementById('btn-nuevo-rol').addEventListener('click', () => formRol());
document.getElementById('btn-nueva-novedad').addEventListener('click', () => formNovedad());

cargar();