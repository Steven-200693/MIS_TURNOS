from datetime import date, time, timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from openpyxl import load_workbook

from .models import (
    AsignacionActaRetribucion, AsignacionSemanal, Empleado, Franja, Novedad,
    Rol, Turno,
)
from .servicios import (
    FESTIVOS_COLOMBIA_2026, _asignaciones_fin_de_semana,
    cambiar_horario, convertir_descanso_en_trabajo, generar_semana,
)


class AsignacionActaRetribucionTests(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre='Supervisor', horas_por_dia=6)
        self.franja = Franja.objects.create(
            rol=self.rol,
            nombre='Mañana',
            hora_inicio='06:00',
        )
        self.supervisores = [
            Empleado.objects.create(
                nombre=f'Supervisor {indice}',
                rol=self.rol,
                franja=self.franja,
            )
            for indice in range(2)
        ]
        self.admin = User.objects.create_user(
            username='admin-acta',
            password='password',
            is_staff=True,
        )

    def test_asigna_aleatoriamente_una_vez_por_mes_y_conserva_la_asignacion(self):
        with patch(
            'horarios.views.random.choice',
            return_value=self.supervisores[1],
        ) as elegir:
            primera = self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-10-28'},
            )
            segunda = self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-10-01'},
            )

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        self.assertEqual(primera.json()['mes'], '2026-10')
        self.assertEqual(
            primera.json()['asignacion']['supervisor_id'],
            self.supervisores[1].id,
        )
        self.assertEqual(
            segunda.json()['asignacion']['supervisor_id'],
            self.supervisores[1].id,
        )
        self.assertEqual(elegir.call_count, 1)
        self.assertEqual(AsignacionActaRetribucion.objects.count(), 1)

    def test_crea_una_asignacion_independiente_para_cada_mes(self):
        with patch(
            'horarios.views.random.choice',
            side_effect=[self.supervisores[0], self.supervisores[1]],
        ) as elegir:
            octubre = self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-10-31'},
            )
            noviembre = self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-11-01'},
            )
            noviembre_repetido = self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-11-27'},
            )

        self.assertEqual(octubre.json()['mes'], '2026-10')
        self.assertEqual(noviembre.json()['mes'], '2026-11')
        self.assertEqual(
            octubre.json()['asignacion']['supervisor_id'],
            self.supervisores[0].id,
        )
        self.assertEqual(
            noviembre.json()['asignacion']['supervisor_id'],
            self.supervisores[1].id,
        )
        self.assertEqual(
            noviembre_repetido.json()['asignacion']['supervisor_id'],
            self.supervisores[1].id,
        )
        self.assertEqual(elegir.call_count, 2)
        self.assertEqual(AsignacionActaRetribucion.objects.count(), 2)

    def test_admin_puede_reasignar_el_acta_del_mes(self):
        self.client.force_login(self.admin)
        respuesta = self.client.post(
            '/api/acta-retribucion/reasignar/',
            data={
                'fecha': '2026-10-01',
                'supervisor_id': self.supervisores[0].id,
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.json()['asignacion']['supervisor_id'],
            self.supervisores[0].id,
        )
        self.assertEqual(AsignacionActaRetribucion.objects.count(), 1)
        self.assertEqual(
            self.client.get(
                '/api/acta-retribucion/',
                {'fecha': '2026-10-31'},
            ).json()['asignacion']['supervisor_id'],
            self.supervisores[0].id,
        )

    def test_reasignar_requiere_administrador_y_supervisor_activo(self):
        cuerpo = {
            'fecha': '2026-10-01',
            'supervisor_id': self.supervisores[0].id,
        }
        no_autorizado = self.client.post(
            '/api/acta-retribucion/reasignar/',
            data=cuerpo,
            content_type='application/json',
        )
        self.assertEqual(no_autorizado.status_code, 403)

        self.client.force_login(self.admin)
        fecha_invalida = self.client.post(
            '/api/acta-retribucion/reasignar/',
            data={'fecha': [], 'supervisor_id': self.supervisores[0].id},
            content_type='application/json',
        )
        self.assertEqual(fecha_invalida.status_code, 400)

        self.supervisores[0].activo = False
        self.supervisores[0].save(update_fields=['activo'])
        inactivo = self.client.post(
            '/api/acta-retribucion/reasignar/',
            data=cuerpo,
            content_type='application/json',
        )
        self.assertEqual(inactivo.status_code, 400)


class LimpiarSemanaTests(TestCase):
    def setUp(self):
        rol = Rol.objects.create(nombre='Técnico', horas_por_dia=7)
        franja = Franja.objects.create(
            rol=rol, nombre='Mañana', hora_inicio='06:00'
        )
        self.empleado = Empleado.objects.create(
            nombre='Técnico de prueba', rol=rol, franja=franja
        )
        self.lunes = date(2026, 10, 19)
        self.admin = User.objects.create_user(
            username='admin', password='password', is_staff=True
        )

    def test_limpia_y_permite_regenerar_sin_perder_franja_ni_novedad(self):
        franja_id = self.empleado.franja_id
        self.empleado.franja = None
        self.empleado.save()
        Turno.objects.create(
            empleado=self.empleado,
            fecha=self.lunes,
            franja_id=franja_id,
            manual=True,
        )
        Turno.objects.create(
            empleado=self.empleado,
            fecha=self.lunes + timedelta(days=7),
            franja_id=franja_id,
        )
        novedad = Novedad.objects.create(
            empleado=self.empleado,
            tipo='VACACIONES',
            fecha_inicio=self.lunes,
            fecha_fin=self.lunes,
        )
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            '/api/limpiar/', {'fecha': self.lunes.isoformat()}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['limpiados'], 1)
        turno_limpio = Turno.objects.get(fecha=self.lunes)
        self.assertIsNone(turno_limpio.inicio)
        self.assertIsNone(turno_limpio.fin)
        self.assertFalse(turno_limpio.descanso)
        self.assertEqual(turno_limpio.franja_id, franja_id)
        self.assertTrue(
            Turno.objects.filter(fecha=self.lunes + timedelta(days=7)).exists()
        )
        self.assertTrue(Novedad.objects.filter(pk=novedad.pk).exists())

        respuesta_generar = self.client.post(
            '/api/generar/', {'fecha': self.lunes.isoformat()}
        )

        self.assertEqual(respuesta_generar.status_code, 200)
        turnos_regenerados = Turno.objects.filter(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
        )
        self.assertEqual(turnos_regenerados.count(), 7)
        self.assertTrue(
            turnos_regenerados.filter(inicio__isnull=False, fin__isnull=False).exists()
        )
        self.assertEqual(
            Turno.objects.get(empleado=self.empleado, fecha=self.lunes).novedad,
            'VACACIONES',
        )

    def test_requiere_administrador(self):
        respuesta = self.client.post(
            '/api/limpiar/', {'fecha': self.lunes.isoformat()}
        )

        self.assertEqual(respuesta.status_code, 403)

    def test_rechaza_fecha_invalida(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post('/api/limpiar/', {'fecha': 'fecha-invalida'})

        self.assertEqual(respuesta.status_code, 400)

    def test_novedad_de_varias_semanas_se_aplica_al_regenerar_turnos_existentes(self):
        self.client.force_login(self.admin)
        semanas = [
            self.lunes - timedelta(days=7),
            self.lunes,
            self.lunes + timedelta(days=7),
            self.lunes + timedelta(days=14),
        ]
        for lunes in semanas:
            generar_semana(lunes)

        turno_manual = Turno.objects.get(
            empleado=self.empleado,
            fecha=self.lunes + timedelta(days=1),
        )
        turno_manual.manual = True
        turno_manual.save(update_fields=['manual'])

        respuesta = self.client.post(
            '/api/novedades/guardar/',
            data={
                'empleado_id': self.empleado.id,
                'tipo': 'INCAPACIDAD',
                'fecha_inicio': (self.lunes - timedelta(days=5)).isoformat(),
                'fecha_fin': (self.lunes + timedelta(days=14)).isoformat(),
                'nota': '',
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['semanas'], 4)
        for fecha in (
            self.lunes - timedelta(days=5),
            self.lunes + timedelta(days=1),
            self.lunes + timedelta(days=13),
            self.lunes + timedelta(days=14),
        ):
            turno = Turno.objects.get(empleado=self.empleado, fecha=fecha)
            self.assertEqual(
                turno.novedad,
                'INCAPACIDAD',
                fecha.isoformat(),
            )
            self.assertIsNone(turno.inicio)
            self.assertIsNone(turno.fin)

        respuesta_semana = self.client.get(
            '/api/semana/', {'fecha': self.lunes.isoformat()}
        )
        empleado_api = next(
            item for item in respuesta_semana.json()['empleados']
            if item['id'] == self.empleado.id
        )
        self.assertEqual(
            empleado_api['turnos'][(self.lunes + timedelta(days=1)).isoformat()]
            ['novedad'],
            'INCAPACIDAD',
        )

    def test_api_semana_indica_festivos_colombianos_de_2026(self):
        respuesta = self.client.get(
            '/api/semana/', {'fecha': '2026-12-08'}
        )

        self.assertEqual(respuesta.status_code, 200)
        festivos = {
            item['fecha']: item['nombre']
            for item in respuesta.json()['festivos']
        }
        self.assertEqual(
            festivos,
            {'2026-12-08': 'Inmaculada Concepción'},
        )

    def test_api_semana_no_muestra_festivos_fuera_del_calendario_2026(self):
        respuesta = self.client.get(
            '/api/semana/', {'fecha': '2027-12-08'}
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['festivos'], [])

    def test_exporta_excel_con_turnos_y_dias_de_descanso(self):
        generar_semana(self.lunes)
        rol_supervisor = Rol.objects.create(
            nombre='Supervisor', horas_por_dia=6
        )
        franja_supervisor = Franja.objects.create(
            rol=rol_supervisor,
            nombre='Supervisor 9 a 3',
            hora_inicio='09:00',
        )
        supervisor = Empleado.objects.create(
            nombre='Supervisor de prueba',
            rol=rol_supervisor,
            franja=franja_supervisor,
        )
        franja_supervisor_tarde = Franja.objects.create(
            rol=rol_supervisor,
            nombre='Supervisor 12 a 6',
            hora_inicio='12:00',
        )
        supervisor_tarde = Empleado.objects.create(
            nombre='Supervisor tarde de prueba',
            rol=rol_supervisor,
            franja=franja_supervisor_tarde,
        )
        Turno.objects.create(
            empleado=supervisor,
            franja=franja_supervisor,
            fecha=self.lunes,
            inicio='09:00',
            fin='15:00',
        )
        Turno.objects.create(
            empleado=supervisor_tarde,
            franja=franja_supervisor_tarde,
            fecha=self.lunes,
            inicio='12:00',
            fin='18:00',
        )

        respuesta = self.client.get(
            '/api/semana/exportar-excel/',
            {'fecha': self.lunes.isoformat()},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        self.assertIn('.xlsx', respuesta['Content-Disposition'])
        libro = load_workbook(BytesIO(respuesta.content), data_only=True)
        hoja = libro['Horario semanal']
        self.assertEqual(hoja['A3'].value, 'Rol')
        self.assertEqual(hoja['B3'].value, 'Empleado')
        self.assertEqual(hoja['C3'].value, 'Franja')
        self.assertEqual(hoja['D3'].value, 'Lun 19/10')
        fila_tecnico = next(
            fila for fila in range(4, hoja.max_row + 1)
            if hoja.cell(fila, 2).value == self.empleado.nombre
        )
        fila_supervisor = next(
            fila for fila in range(4, hoja.max_row + 1)
            if hoja.cell(fila, 2).value == supervisor.nombre
        )
        fila_supervisor_tarde = next(
            fila for fila in range(4, hoja.max_row + 1)
            if hoja.cell(fila, 2).value == supervisor_tarde.nombre
        )
        self.assertEqual(
            hoja.cell(fila_supervisor, 4).fill.fgColor.rgb[-6:],
            'FCA5A5',
        )
        self.assertEqual(
            hoja.cell(fila_supervisor_tarde, 4).fill.fgColor.rgb[-6:],
            'BBF7D0',
        )
        valores_turno = [
            hoja.cell(fila_tecnico, columna).value
            for columna in range(4, 11)
        ]
        self.assertIn('Descanso', valores_turno)
        self.assertTrue(any(
            isinstance(valor, str) and '–' in valor
            for valor in valores_turno
        ))
        self.assertEqual(hoja.freeze_panes, 'D4')

    def test_exportar_excel_rechaza_fecha_invalida(self):
        respuesta = self.client.get(
            '/api/semana/exportar-excel/',
            {'fecha': 'fecha-invalida'},
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('error', respuesta.json())

    def test_dashboard_descansos_resume_historial_por_rol_y_fines_de_semana(self):
        supervisor_rol = Rol.objects.create(
            nombre='Supervisor', horas_por_dia=6
        )
        supervisor_franja = Franja.objects.create(
            rol=supervisor_rol,
            nombre='Supervisor mañana',
            hora_inicio='06:00',
        )
        supervisor = Empleado.objects.create(
            nombre='Supervisora de prueba',
            rol=supervisor_rol,
            franja=supervisor_franja,
        )
        for fecha in (
            date(2026, 1, 3),
            date(2026, 1, 4),
            date(2026, 1, 5),
            date(2026, 1, 10),
            date(2026, 1, 11),
        ):
            Turno.objects.create(
                empleado=self.empleado,
                franja=self.empleado.franja,
                fecha=fecha,
                descanso=fecha in {
                    date(2026, 1, 3),
                    date(2026, 1, 4),
                    date(2026, 1, 5),
                    date(2026, 1, 10),
                },
                inicio=None if fecha in {
                    date(2026, 1, 3),
                    date(2026, 1, 4),
                    date(2026, 1, 5),
                    date(2026, 1, 10),
                } else '06:00',
                fin=None if fecha in {
                    date(2026, 1, 3),
                    date(2026, 1, 4),
                    date(2026, 1, 5),
                    date(2026, 1, 10),
                } else '12:00',
            )
        for fecha in (date(2026, 1, 3), date(2026, 1, 4)):
            Turno.objects.create(
                empleado=supervisor,
                franja=supervisor_franja,
                fecha=fecha,
                descanso=True,
            )

        respuesta = self.client.get('/api/dashboard/descansos/')

        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        tecnico = datos['grupos']['Técnico'][0]
        self.assertEqual(tecnico['nombre'], self.empleado.nombre)
        self.assertEqual(tecnico['total_descansos'], 4)
        self.assertEqual(tecnico['sabados_descanso'], 2)
        self.assertEqual(tecnico['domingos_descanso'], 1)
        self.assertEqual(tecnico['dias_descanso_fin_semana'], 3)
        self.assertEqual(tecnico['fines_semana_completos'], 1)
        self.assertEqual(tecnico['fines_semana_observados'], 2)
        self.assertEqual(datos['grupos']['Supervisor'][0]['total_descansos'], 2)
        self.assertEqual(datos['fecha_inicio'], '2026-01-03')
        self.assertEqual(datos['fecha_fin'], '2026-01-11')
        self.assertEqual(
            datos['resumen']['Técnico']['promedio_descansos_fin_semana'],
            3,
        )

        Turno.objects.filter(
            empleado=self.empleado,
            fecha=date(2026, 1, 3),
        ).update(descanso=False)
        respuesta_actualizada = self.client.get('/api/dashboard/descansos/')
        tecnico_actualizado = respuesta_actualizada.json()['grupos']['Técnico'][0]
        self.assertEqual(tecnico_actualizado['total_descansos'], 3)
        self.assertEqual(tecnico_actualizado['sabados_descanso'], 1)
        self.assertEqual(tecnico_actualizado['dias_descanso_fin_semana'], 2)
        self.assertEqual(tecnico_actualizado['fines_semana_completos'], 0)

    def test_dashboard_descansos_devuelve_grupos_vacios_sin_historial(self):
        respuesta = self.client.get('/api/dashboard/descansos/')

        self.assertEqual(respuesta.status_code, 200)
        self.assertIsNone(respuesta.json()['fecha_inicio'])
        self.assertIsNone(respuesta.json()['fecha_fin'])
        self.assertEqual(respuesta.json()['grupos']['Técnico'][0]['total_descansos'], 0)

    def test_dashboard_muestra_festivos_trabajados_y_descansados_solo_con_fecha(self):
        fecha_descanso = date(2026, 1, 1)
        fecha_trabajo = date(2026, 1, 12)
        Turno.objects.create(
            empleado=self.empleado,
            franja=self.empleado.franja,
            fecha=fecha_descanso,
            descanso=True,
        )
        Turno.objects.create(
            empleado=self.empleado,
            franja=self.empleado.franja,
            fecha=fecha_trabajo,
            inicio='06:00',
            fin='13:00',
        )

        respuesta = self.client.get('/api/dashboard/descansos/')

        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        tecnico = datos['grupos']['Técnico'][0]
        self.assertEqual(tecnico['total_festivos_descanso'], 1)
        self.assertEqual(tecnico['festivos_descanso'], ['2026-01-01'])
        self.assertEqual(tecnico['total_festivos_trabajados'], 1)
        self.assertEqual(tecnico['festivos_trabajados'], ['2026-01-12'])
        self.assertEqual(
            datos['resumen']['Técnico']['promedio_festivos_descanso'],
            1,
        )
        self.assertEqual(
            datos['resumen']['Técnico']['promedio_festivos_trabajados'],
            1,
        )


class RotacionFinDeSemanaSupervisoresTests(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre='Supervisor', horas_por_dia=6)
        self.franjas = [
            Franja.objects.create(
                rol=self.rol,
                nombre=f'Franja {hora}',
                hora_inicio=f'{hora:02d}:00',
            )
            for hora in (6, 9, 12, 13)
        ]
        self.supervisores = [
            Empleado.objects.create(
                nombre=f'Supervisor {indice}',
                rol=self.rol,
                franja=franja,
                preferencia_descanso='FINDE',
            )
            for indice, franja in enumerate(self.franjas)
        ]
        self.lunes = date(2026, 10, 19)

    def test_festivo_asigna_un_supervisor_remoto_doce_horas_y_libera_a_los_demas(self):
        festivo = date(2026, 11, 2)

        generar_semana(festivo)

        turnos = [
            Turno.objects.get(empleado=supervisor, fecha=festivo)
            for supervisor in self.supervisores
        ]
        trabajando = [turno for turno in turnos if not turno.descanso]
        descansando = [turno for turno in turnos if turno.descanso]
        self.assertEqual(len(trabajando), 1)
        self.assertEqual(len(descansando), 3)
        self.assertEqual(trabajando[0].inicio.isoformat(), '06:00:00')
        self.assertEqual(trabajando[0].fin.isoformat(), '18:00:00')
        self.assertTrue(trabajando[0].remoto)

        generar_semana(festivo)

        turno_guardia = Turno.objects.get(
            empleado=trabajando[0].empleado, fecha=festivo
        )
        self.assertFalse(turno_guardia.descanso)
        self.assertTrue(turno_guardia.remoto)
        self.assertEqual(
            Turno.objects.filter(
                empleado__in=self.supervisores,
                fecha=festivo,
                descanso=False,
                remoto=True,
            ).count(),
            1,
        )

    def test_rotacion_de_festivos_cambia_supervisor_y_manual_asigna_ds(self):
        festivo_uno = date(2026, 11, 2)
        festivo_dos = date(2026, 11, 16)

        generar_semana(festivo_uno)
        guardia_uno = Turno.objects.get(
            empleado__in=self.supervisores,
            fecha=festivo_uno,
            descanso=False,
        ).empleado
        generar_semana(festivo_dos)
        guardia_dos = Turno.objects.get(
            empleado__in=self.supervisores,
            fecha=festivo_dos,
            descanso=False,
        ).empleado

        self.assertNotEqual(guardia_uno.id, guardia_dos.id)

        supervisor_objetivo = next(
            supervisor for supervisor in self.supervisores
            if supervisor.id != guardia_dos.id
        )
        convertir_descanso_en_trabajo(supervisor_objetivo, festivo_dos)

        guardia_manual = Turno.objects.get(
            empleado=supervisor_objetivo,
            fecha=festivo_dos,
        )
        self.assertFalse(guardia_manual.descanso)
        self.assertEqual(guardia_manual.inicio.isoformat(), '06:00:00')
        self.assertEqual(guardia_manual.fin.isoformat(), '18:00:00')
        self.assertTrue(guardia_manual.remoto)
        self.assertTrue(guardia_manual.manual)
        self.assertEqual(
            Turno.objects.filter(
                empleado__in=self.supervisores,
                fecha=festivo_dos,
                descanso=False,
                remoto=True,
            ).count(),
            1,
        )

    def test_cambio_manual_de_horario_festivo_conserva_ds_de_doce_horas(self):
        festivo = date(2026, 11, 2)
        generar_semana(festivo)
        guardia = Turno.objects.get(
            empleado__in=self.supervisores,
            fecha=festivo,
            descanso=False,
        ).empleado

        cambiar_horario(guardia, festivo, time(9, 0))

        turno = Turno.objects.get(empleado=guardia, fecha=festivo)
        self.assertEqual(turno.inicio, time(6, 0))
        self.assertEqual(turno.fin, time(18, 0))
        self.assertTrue(turno.remoto)
        self.assertTrue(turno.manual)

    def test_intercambio_de_patron_conserva_dos_libres_y_persiste_al_regenerar(self):
        admin = User.objects.create_user(
            username='admin-supervisores', password='password', is_staff=True
        )
        self.client.force_login(admin)
        generar_semana(self.lunes)
        sabado = self.lunes + timedelta(days=5)
        domingo = sabado + timedelta(days=1)
        empleado_trabaja_sabado = Turno.objects.get(
            fecha=sabado, descanso=False, empleado__in=self.supervisores
        ).empleado
        empleado_trabaja_domingo = Turno.objects.get(
            fecha=domingo, descanso=False, empleado__in=self.supervisores
        ).empleado
        empleado_libre = next(
            empleado
            for empleado in self.supervisores
            if Turno.objects.get(empleado=empleado, fecha=sabado).descanso
            and Turno.objects.get(empleado=empleado, fecha=domingo).descanso
        )

        respuesta = self.client.post(
            '/api/supervisores/fin-de-semana/intercambiar/',
            data={
                'empleado_id': empleado_trabaja_sabado.id,
                'companero_id': empleado_libre.id,
                'fecha': sabado.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        for regenerar in (False, True):
            if regenerar:
                generar_semana(self.lunes)
            turnos_sabado = [
                Turno.objects.get(empleado=empleado, fecha=sabado)
                for empleado in self.supervisores
            ]
            turnos_domingo = [
                Turno.objects.get(empleado=empleado, fecha=domingo)
                for empleado in self.supervisores
            ]
            self.assertEqual(
                sum(turno.descanso for turno in turnos_sabado), 3
            )
            self.assertEqual(
                sum(
                    Turno.objects.get(
                        empleado=empleado, fecha=sabado
                    ).descanso
                    and Turno.objects.get(
                        empleado=empleado, fecha=domingo
                    ).descanso
                    for empleado in self.supervisores
                ),
                2,
            )
            trabajando_sabado = [
                turno for turno in turnos_sabado if not turno.descanso
            ]
            trabajando_domingo = [
                turno for turno in turnos_domingo if not turno.descanso
            ]
            self.assertEqual(len(trabajando_sabado), 1)
            self.assertEqual(len(trabajando_domingo), 1)
            self.assertEqual(
                trabajando_sabado[0].empleado_id, empleado_libre.id
            )
            self.assertEqual(
                trabajando_domingo[0].empleado_id, empleado_trabaja_domingo.id
            )
            self.assertEqual(trabajando_sabado[0].inicio.isoformat(), '06:00:00')
            self.assertEqual(trabajando_sabado[0].fin.isoformat(), '18:00:00')
            self.assertFalse(trabajando_sabado[0].remoto)
            self.assertEqual(trabajando_domingo[0].inicio.isoformat(), '06:00:00')
            self.assertEqual(trabajando_domingo[0].fin.isoformat(), '18:00:00')
            self.assertTrue(trabajando_domingo[0].remoto)

    def test_intercambio_rechaza_supervisor_con_novedad(self):
        admin = User.objects.create_user(
            username='admin-novedad', password='password', is_staff=True
        )
        self.client.force_login(admin)
        generar_semana(self.lunes)
        sabado = self.lunes + timedelta(days=5)
        trabajador = Turno.objects.get(
            fecha=sabado, descanso=False, empleado__in=self.supervisores
        ).empleado
        libre = next(
            empleado for empleado in self.supervisores
            if Turno.objects.get(empleado=empleado, fecha=sabado).descanso
            and Turno.objects.get(
                empleado=empleado, fecha=sabado + timedelta(days=1)
            ).descanso
        )
        Turno.objects.filter(
            empleado=trabajador, fecha=sabado
        ).update(novedad='PERMISO')

        respuesta = self.client.post(
            '/api/supervisores/fin-de-semana/intercambiar/',
            data={
                'empleado_id': trabajador.id,
                'companero_id': libre.id,
                'fecha': sabado.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('novedad', respuesta.json()['error'])

    def test_transfiere_turno_domingo_a_supervisor_libre_y_deja_dos_dias_de_descanso(self):
        admin = User.objects.create_user(
            username='admin-domingo', password='password', is_staff=True
        )
        self.client.force_login(admin)
        generar_semana(self.lunes)
        sabado = self.lunes + timedelta(days=5)
        domingo = sabado + timedelta(days=1)
        trabajador_domingo = Turno.objects.get(
            fecha=domingo, descanso=False, empleado__in=self.supervisores
        ).empleado
        supervisor_libre = next(
            empleado
            for empleado in self.supervisores
            if Turno.objects.get(empleado=empleado, fecha=sabado).descanso
            and Turno.objects.get(empleado=empleado, fecha=domingo).descanso
        )
        Turno.objects.filter(
            empleado=trabajador_domingo, fecha=domingo
        ).update(inicio='06:00', fin='12:00', remoto=True, manual=True)

        respuesta = self.client.post(
            '/api/supervisores/fin-de-semana/intercambiar/',
            data={
                'empleado_id': trabajador_domingo.id,
                'companero_id': supervisor_libre.id,
                'fecha': domingo.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        for regenerar in (False, True):
            if regenerar:
                generar_semana(self.lunes)
            for fecha in (sabado, domingo):
                self.assertTrue(Turno.objects.get(
                    empleado=trabajador_domingo, fecha=fecha
                ).descanso)
            turno_transferido = Turno.objects.get(
                empleado=supervisor_libre, fecha=domingo
            )
            self.assertFalse(turno_transferido.descanso)
            self.assertEqual(turno_transferido.inicio.isoformat(), '06:00:00')
            self.assertEqual(turno_transferido.fin.isoformat(), '18:00:00')
            self.assertTrue(turno_transferido.remoto)
            self.assertTrue(turno_transferido.manual)

            turnos_supervisores = Turno.objects.filter(
                empleado__in=self.supervisores,
                fecha__in=(sabado, domingo),
            )
            libres_completos = sum(
                Turno.objects.get(
                    empleado=empleado, fecha=sabado
                ).descanso
                and Turno.objects.get(
                    empleado=empleado, fecha=domingo
                ).descanso
                for empleado in self.supervisores
            )
            self.assertEqual(libres_completos, 2)
            self.assertEqual(
                turnos_supervisores.filter(fecha=sabado, descanso=False).count(),
                1,
            )
            self.assertEqual(
                turnos_supervisores.filter(fecha=domingo, descanso=False).count(),
                1,
            )

    def test_cobertura_remota_y_descansos_rotan_equitativamente_en_cuatro_semanas(self):
        dias_trabajados_fin_de_semana = {
            empleado.id: [] for empleado in self.supervisores
        }
        fines_de_semana_libres = {empleado.id: 0 for empleado in self.supervisores}

        for numero_semana in range(4):
            lunes = self.lunes + timedelta(days=7 * numero_semana)
            generar_semana(lunes)
            sabado = lunes + timedelta(days=5)
            domingo = lunes + timedelta(days=6)

            jornadas_sabado = list(Turno.objects.filter(
                empleado__in=self.supervisores,
                fecha=sabado,
                descanso=False,
                inicio__isnull=False,
            ))
            jornadas_domingo = list(Turno.objects.filter(
                empleado__in=self.supervisores,
                fecha=domingo,
                descanso=False,
                inicio__isnull=False,
            ))
            remotos = [turno for turno in jornadas_domingo if turno.remoto]
            self.assertEqual(len(jornadas_sabado), 1)
            self.assertFalse(jornadas_sabado[0].remoto)
            self.assertEqual(len(jornadas_domingo), 1)
            self.assertEqual(len(remotos), 1)

            for empleado in self.supervisores:
                turnos = list(Turno.objects.filter(
                    empleado=empleado,
                    fecha__range=(lunes, domingo),
                ))
                jornadas_finde = [
                    turno for turno in turnos
                    if turno.fecha.weekday() in (5, 6)
                    and not turno.descanso
                    and turno.inicio
                ]
                descanso_sabado = Turno.objects.get(
                    empleado=empleado, fecha=sabado
                ).descanso
                descanso_domingo = Turno.objects.get(
                    empleado=empleado, fecha=domingo
                ).descanso

                if jornadas_finde:
                    self.assertEqual(len(jornadas_finde), 1)
                    jornada = jornadas_finde[0]
                    self.assertEqual(jornada.inicio.isoformat(), '06:00:00')
                    self.assertEqual(jornada.fin.isoformat(), '18:00:00')
                    self.assertEqual(jornada.remoto, jornada.fecha == domingo)
                    if jornada.fecha == domingo:
                        self.assertTrue(descanso_sabado)
                        self.assertFalse(descanso_domingo)
                    else:
                        self.assertFalse(descanso_sabado)
                        self.assertTrue(descanso_domingo)
                    dias_trabajados_fin_de_semana[empleado.id].append(
                        jornada.fecha.weekday()
                    )
                else:
                    self.assertTrue(descanso_sabado)
                    self.assertTrue(descanso_domingo)
                    fines_de_semana_libres[empleado.id] += 1
                esperado = 0
                for turno in turnos:
                    if turno.novedad:
                        continue
                    if turno.fecha in FESTIVOS_COLOMBIA_2026:
                        if not turno.descanso and turno.inicio and turno.fin:
                            esperado += 12
                    elif turno.fecha.weekday() < 5:
                        esperado += self.rol.horas_por_dia
                    elif not turno.descanso and turno.inicio and turno.fin:
                        esperado += 12

                respuesta = self.client.get(
                    f'/api/semana/?fecha={lunes.isoformat()}'
                )
                datos = respuesta.json()
                personal = next(
                    item for item in datos['empleados']
                    if item['id'] == empleado.id
                )
                self.assertEqual(personal['horas_semana'], esperado)
                self.assertEqual(personal['horas_meta'], esperado)
                if jornadas_finde and jornadas_finde[0].fecha == domingo:
                    fecha_remota = domingo.isoformat()
                    self.assertTrue(personal['turnos'][fecha_remota]['remoto'])

        for empleado in self.supervisores:
            self.assertEqual(len(dias_trabajados_fin_de_semana[empleado.id]), 2)
            self.assertEqual(set(dias_trabajados_fin_de_semana[empleado.id]), {5, 6})
            self.assertEqual(fines_de_semana_libres[empleado.id], 2)

    def test_supervisores_conservan_su_franja_configurada_cada_semana(self):
        for numero_semana in range(4):
            lunes = self.lunes + timedelta(days=7 * numero_semana)
            generar_semana(lunes)
            for supervisor in self.supervisores:
                turnos = list(Turno.objects.filter(
                    empleado=supervisor,
                    fecha__range=(lunes, lunes + timedelta(days=6)),
                ).order_by('fecha'))
                self.assertEqual(len(turnos), 7)
                self.assertEqual(
                    {turno.franja_id for turno in turnos},
                    {supervisor.franja_id},
                )
                for turno in turnos[:5]:
                    if (
                        turno.novedad
                        or turno.fecha in FESTIVOS_COLOMBIA_2026
                    ):
                        continue
                    self.assertEqual(
                        turno.inicio.strftime('%H:%M'),
                        supervisor.franja.hora_inicio,
                    )

            respuesta = self.client.get(
                '/api/semana/',
                {'fecha': lunes.isoformat()},
            )
            datos_empleados = {
                item['id']: item for item in respuesta.json()['empleados']
            }
            for supervisor in self.supervisores:
                turno = Turno.objects.filter(
                    empleado=supervisor,
                    fecha__range=(lunes, lunes + timedelta(days=6)),
                ).first()
                franja = Franja.objects.get(pk=turno.franja_id)
                self.assertEqual(datos_empleados[supervisor.id]['franja'], franja.nombre)

    def test_turno_de_sabado_siempre_es_presencial_de_seis_a_dieciocho(self):
        generar_semana(self.lunes)
        asignaciones_fin_de_semana, _ = _asignaciones_fin_de_semana(self.lunes)
        empleado_id = next(
            empleado_id
            for empleado_id, dia in asignaciones_fin_de_semana.items()
            if dia == 5
        )
        sabado = self.lunes + timedelta(days=5)
        Turno.objects.filter(empleado_id=empleado_id, fecha=sabado).update(
            inicio='06:00',
            fin='12:00',
            remoto=True,
            manual=True,
        )

        generar_semana(self.lunes)

        turno = Turno.objects.get(empleado_id=empleado_id, fecha=sabado)
        self.assertFalse(turno.descanso)
        self.assertEqual(turno.inicio.isoformat(), '06:00:00')
        self.assertEqual(turno.fin.isoformat(), '18:00:00')
        self.assertFalse(turno.remoto)
        self.assertFalse(turno.manual)


class RotacionTecnicosSinFranjaTests(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre='Tecnico', horas_por_dia=7)
        self.manana = Franja.objects.create(
            rol=self.rol, nombre='Mañana', hora_inicio='06:00'
        )
        self.tarde = Franja.objects.create(
            rol=self.rol, nombre='Tarde', hora_inicio='13:00'
        )
        self.noche = Franja.objects.create(
            rol=self.rol, nombre='Noche', hora_inicio='16:00'
        )
        self.madrugada = Franja.objects.create(
            rol=self.rol, nombre='Madrugada', hora_inicio='23:00'
        )
        self.tecnicos = [
            Empleado.objects.create(nombre=f'Técnico {indice}', rol=self.rol)
            for indice in range(7)
        ]
        self.tecnico_fijo = Empleado.objects.create(
            nombre='Técnico fijo',
            rol=self.rol,
            franja=self.madrugada,
        )
        self.lunes = date(2026, 10, 19)

    def _franjas_de_semana(self, empleado, lunes):
        return set(Turno.objects.filter(
            empleado=empleado,
            fecha__range=(lunes, lunes + timedelta(days=6)),
        ).values_list('franja_id', flat=True))

    def test_tecnico_nuevo_inicia_turnos_en_su_fecha_de_ingreso(self):
        admin = User.objects.create_user(
            username='admin-ingreso-tecnico', password='password', is_staff=True
        )
        self.client.force_login(admin)
        fecha_ingreso = self.lunes + timedelta(days=2)

        respuesta = self.client.post(
            '/api/empleados/guardar/',
            data={
                'nombre': 'Técnico nuevo',
                'rol_id': self.rol.id,
                'fecha_ingreso': fecha_ingreso.isoformat(),
                'franja_id': self.manana.id,
                'preferencia_descanso': 'CUALQUIERA',
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        empleado = Empleado.objects.get(pk=respuesta.json()['id'])
        self.assertEqual(empleado.fecha_ingreso, fecha_ingreso)
        generar_semana(self.lunes)
        self.assertFalse(Turno.objects.filter(
            empleado=empleado,
            fecha__lt=fecha_ingreso,
        ).exists())
        self.assertTrue(Turno.objects.filter(
            empleado=empleado,
            fecha__gte=fecha_ingreso,
            fecha__lte=self.lunes + timedelta(days=6),
        ).exists())

        respuesta_semana = self.client.get(
            '/api/semana/', {'fecha': self.lunes.isoformat()}
        )
        empleado_api = next(
            fila for fila in respuesta_semana.json()['empleados']
            if fila['id'] == empleado.id
        )
        self.assertEqual(
            empleado_api['turnos'].get(self.lunes.isoformat()),
            None,
        )
        self.assertEqual(
            empleado_api['turnos'].get((self.lunes + timedelta(days=1)).isoformat()),
            None,
        )

    def test_api_exige_fecha_ingreso_para_nuevo_empleado(self):
        admin = User.objects.create_user(
            username='admin-sin-fecha', password='password', is_staff=True
        )
        self.client.force_login(admin)

        respuesta = self.client.post(
            '/api/empleados/guardar/',
            data={
                'nombre': 'Técnico sin fecha',
                'rol_id': self.rol.id,
                'franja_id': self.manana.id,
                'preferencia_descanso': 'CUALQUIERA',
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('fecha de ingreso', respuesta.json()['error'])

    def test_festivo_asigna_un_tecnico_por_franja_y_descansa_el_restante(self):
        festivo = date(2026, 11, 2)
        lunes_festivo = festivo - timedelta(days=festivo.weekday())
        generar_semana(festivo)

        for franja in (
            self.manana, self.tarde, self.noche, self.madrugada
        ):
            turnos = list(Turno.objects.filter(
                franja=franja,
                fecha=festivo,
                empleado__activo=True,
            ))
            trabajando = [
                turno for turno in turnos
                if not turno.descanso and not turno.novedad
            ]
            descansando = [turno for turno in turnos if turno.descanso]
            self.assertEqual(len(trabajando), 1, franja.nombre)
            self.assertEqual(
                len(descansando), len(turnos) - 1, franja.nombre
            )
            self.assertEqual(
                trabajando[0].inicio.strftime('%H:%M'), franja.hora_inicio
            )

        for empleado in self.tecnicos + [self.tecnico_fijo]:
            descansos_semana = Turno.objects.filter(
                empleado=empleado,
                fecha__range=(lunes_festivo, lunes_festivo + timedelta(days=6)),
                descanso=True,
                novedad='',
            ).count()
            self.assertEqual(descansos_semana, 1, empleado.nombre)

        asignaciones_antes = {
            franja.id: Turno.objects.get(
                franja=franja, fecha=festivo, descanso=False
            ).empleado_id
            for franja in (
                self.manana, self.tarde, self.noche, self.madrugada
            )
        }
        generar_semana(festivo)
        for empleado in self.tecnicos + [self.tecnico_fijo]:
            self.assertEqual(
                Turno.objects.filter(
                    empleado=empleado,
                    fecha__range=(lunes_festivo, lunes_festivo + timedelta(days=6)),
                    descanso=True,
                    novedad='',
                ).count(),
                1,
                empleado.nombre,
            )
        self.assertEqual(
            asignaciones_antes,
            {
                franja.id: Turno.objects.get(
                    franja=franja, fecha=festivo, descanso=False
                ).empleado_id
                for franja in (
                    self.manana, self.tarde, self.noche, self.madrugada
                )
            },
        )

    def test_guardia_festiva_prioriza_quien_tuvo_menos_trabajo_en_fin_de_semana(self):
        festivo = date(2026, 11, 2)
        generar_semana(festivo)
        sabado = festivo - timedelta(days=2)
        domingo = festivo - timedelta(days=1)
        franja = self.manana
        equipo = list(Empleado.objects.filter(
            activo=True,
            turno__fecha=festivo,
            turno__franja=franja,
        ).distinct().order_by('id'))
        self.assertGreaterEqual(len(equipo), 2)
        persona_menos_carga = equipo[0]
        persona_mas_carga = equipo[1]

        for fecha in (sabado, domingo):
            Turno.objects.filter(
                empleado=persona_menos_carga, fecha=fecha
            ).update(descanso=True, inicio=None, fin=None, manual=True)
            Turno.objects.filter(
                empleado=persona_mas_carga, fecha=fecha
            ).update(
                descanso=False,
                inicio=franja.hora_inicio,
                fin='13:00',
                manual=True,
            )

        generar_semana(festivo)

        guardia = Turno.objects.get(
            franja=franja, fecha=festivo, descanso=False
        )
        self.assertEqual(guardia.empleado_id, persona_menos_carga.id)

    def test_tecnicos_sin_franja_rotan_el_lunes_y_mantienen_franja_toda_la_semana(self):
        generar_semana(self.lunes)
        asignaciones_primera_semana = {
            empleado.id: self._franjas_de_semana(empleado, self.lunes)
            for empleado in self.tecnicos
        }

        self.assertEqual(
            {franja_id for franjas in asignaciones_primera_semana.values()
             for franja_id in franjas},
            {self.manana.id, self.tarde.id, self.noche.id, self.madrugada.id},
        )
        for empleado in self.tecnicos:
            franja_ids = asignaciones_primera_semana[empleado.id]
            self.assertEqual(len(franja_ids), 1)
            franja_id = next(iter(franja_ids))
            turnos = list(Turno.objects.filter(
                empleado=empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            ))
            self.assertEqual(len(turnos), 7)
            self.assertEqual(
                sum(not turno.descanso and not turno.novedad for turno in turnos),
                6,
            )
            for turno in turnos:
                if turno.descanso or turno.novedad:
                    continue
                esperado = Franja.objects.get(pk=franja_id).hora_inicio
                self.assertEqual(turno.inicio, esperado)

        for franja in (self.manana, self.tarde, self.noche, self.madrugada):
            for dia in range(7):
                fecha = self.lunes + timedelta(days=dia)
                cobertura = Turno.objects.filter(
                    franja=franja,
                    fecha=fecha,
                    descanso=False,
                    novedad='',
                    inicio__isnull=False,
                ).count()
                self.assertGreaterEqual(
                    cobertura,
                    franja.minimo_personas,
                    f"{franja.nombre} sin cobertura el {fecha} ({cobertura}): "
                    f"{list(Turno.objects.filter(franja=franja, fecha=fecha).values_list('empleado__nombre', 'descanso', 'novedad'))}",
                )

        respuesta_semana = self.client.get(
            '/api/semana/',
            {'fecha': self.lunes.isoformat()},
        )
        empleados_api = {
            empleado['id']: empleado
            for empleado in respuesta_semana.json()['empleados']
        }
        for empleado in self.tecnicos:
            turno = Turno.objects.filter(
                empleado=empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            ).first()
            self.assertEqual(
                empleados_api[empleado.id]['franja'],
                turno.franja.nombre,
            )

        # Re-generating is stable, then every technician covers all four shifts.
        generar_semana(self.lunes)
        self.assertEqual(
            asignaciones_primera_semana,
            {
                empleado.id: self._franjas_de_semana(empleado, self.lunes)
                for empleado in self.tecnicos
            },
        )
        franjas_rotadas = {
            empleado.id: set(asignaciones_primera_semana[empleado.id])
            for empleado in self.tecnicos
        }
        for numero_semana in range(1, 4):
            semana = self.lunes + timedelta(days=7 * numero_semana)
            generar_semana(semana)
            for franja in (
                self.manana, self.tarde, self.noche, self.madrugada
            ):
                for dia in range(7):
                    self.assertGreaterEqual(
                        Turno.objects.filter(
                            franja=franja,
                            fecha=semana + timedelta(days=dia),
                            descanso=False,
                            novedad='',
                            inicio__isnull=False,
                        ).count(),
                        franja.minimo_personas,
                    )
            for empleado in self.tecnicos:
                franjas_rotadas[empleado.id].update(
                    self._franjas_de_semana(empleado, semana)
                )
        for empleado in self.tecnicos:
            self.assertGreaterEqual(len(franjas_rotadas[empleado.id]), 2)

        self.assertEqual(self._franjas_de_semana(
            self.tecnico_fijo, self.lunes
        ), {self.madrugada.id})
        self.assertTrue(Turno.objects.filter(
            empleado=self.tecnico_fijo,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            inicio='23:00',
        ).exists())

    def test_novedad_se_conserva_en_la_franja_semanal_asignada(self):
        fecha_vacaciones = self.lunes + timedelta(days=2)
        Novedad.objects.create(
            empleado=self.tecnicos[0],
            tipo='VACACIONES',
            fecha_inicio=fecha_vacaciones,
            fecha_fin=fecha_vacaciones,
        )

        generar_semana(self.lunes)

        turno_vacaciones = Turno.objects.get(
            empleado=self.tecnicos[0], fecha=fecha_vacaciones
        )
        self.assertEqual(turno_vacaciones.novedad, 'VACACIONES')
        self.assertIn(
            turno_vacaciones.franja_id,
            (self.manana.id, self.tarde.id, self.noche.id, self.madrugada.id),
        )

    def test_guarda_cupos_personalizados_y_el_generador_los_respeta(self):
        admin = User.objects.create_user(
            username='admin-cupos', password='password', is_staff=True
        )
        self.client.force_login(admin)
        cupos = {
            self.manana.id: 3,
            self.tarde.id: 1,
            self.noche.id: 2,
            self.madrugada.id: 1,
        }

        respuesta = self.client.post(
            '/api/tecnicos/distribucion/',
            data={
                'fecha': self.lunes.isoformat(),
                'distribucion': [
                    {'franja_id': franja_id, 'cantidad': cantidad}
                    for franja_id, cantidad in cupos.items()
                ],
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            AsignacionSemanal.objects.filter(lunes=self.lunes).count(),
            4,
        )
        generar_semana(self.lunes)
        for franja_id, cantidad in cupos.items():
            asignados = Empleado.objects.filter(
                activo=True,
                franja__isnull=True,
                turno__fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
                turno__franja_id=franja_id,
            ).distinct().count()
            self.assertEqual(asignados, cantidad)
        for dia in range(7):
            cobertura_noche = Turno.objects.filter(
                franja=self.noche,
                fecha=self.lunes + timedelta(days=dia),
                descanso=False,
                novedad='',
                inicio__isnull=False,
            ).count()
            self.assertGreaterEqual(cobertura_noche, self.noche.minimo_personas)
        respuesta_semana = self.client.get(
            '/api/semana/', {'fecha': self.lunes.isoformat()}
        )
        configuracion = respuesta_semana.json()['distribucion_tecnicos']
        self.assertTrue(configuracion['configurada'])
        self.assertEqual(configuracion['total'], 7)
        self.assertEqual(
            {item['id']: item['cantidad'] for item in configuracion['franjas']},
            cupos,
        )

    def test_tecnico_de_noche_trabaja_desde_el_lunes_y_descansa_el_domingo(self):
        cupos = {
            self.manana.id: 2,
            self.tarde.id: 2,
            self.noche.id: 2,
            self.madrugada.id: 1,
        }
        AsignacionSemanal.objects.bulk_create([
            AsignacionSemanal(
                lunes=self.lunes,
                franja_id=franja_id,
                cantidad=cantidad,
            )
            for franja_id, cantidad in cupos.items()
        ])

        generar_semana(self.lunes)

        tecnicos_noche = list(Turno.objects.filter(
            franja=self.noche,
            fecha=self.lunes,
            descanso=False,
        ).values_list('empleado', flat=True))
        self.assertEqual(len(tecnicos_noche), 2)
        tecnico_descansa_domingo = Turno.objects.get(
            empleado__in=tecnicos_noche,
            fecha=self.lunes + timedelta(days=6),
            descanso=True,
        )
        turno_lunes = Turno.objects.get(
            empleado=tecnico_descansa_domingo.empleado,
            fecha=self.lunes,
        )
        self.assertEqual(turno_lunes.inicio.isoformat(), '16:00:00')
        turnos_semana = Turno.objects.filter(
            empleado=tecnico_descansa_domingo.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
        )
        self.assertEqual(
            turnos_semana.filter(descanso=False, novedad='').count(),
            6,
        )
        self.assertEqual(
            Turno.objects.filter(
                franja=self.noche,
                fecha=self.lunes + timedelta(days=6),
                descanso=False,
                novedad='',
                inicio__isnull=False,
            ).count(),
            1,
        )
        for dia in range(7):
            self.assertGreaterEqual(
                Turno.objects.filter(
                    franja=self.noche,
                    fecha=self.lunes + timedelta(days=dia),
                    descanso=False,
                    novedad='',
                    inicio__isnull=False,
                ).count(),
                1,
            )

    def test_permite_un_tecnico_en_noche_y_rechaza_cero(self):
        admin = User.objects.create_user(
            username='admin-cupos-invalidos', password='password', is_staff=True
        )
        self.client.force_login(admin)

        respuesta_permitida = self.client.post(
            '/api/tecnicos/distribucion/',
            data={
                'fecha': self.lunes.isoformat(),
                'distribucion': [
                    {'franja_id': self.manana.id, 'cantidad': 3},
                    {'franja_id': self.tarde.id, 'cantidad': 2},
                    {'franja_id': self.noche.id, 'cantidad': 1},
                    {'franja_id': self.madrugada.id, 'cantidad': 1},
                ],
            },
            content_type='application/json',
        )
        self.assertEqual(respuesta_permitida.status_code, 200)
        self.assertEqual(
            AsignacionSemanal.objects.get(
                lunes=self.lunes, franja=self.noche
            ).cantidad,
            1,
        )

        respuesta_rechazada = self.client.post(
            '/api/tecnicos/distribucion/',
            data={
                'fecha': self.lunes.isoformat(),
                'distribucion': [
                    {'franja_id': self.manana.id, 'cantidad': 4},
                    {'franja_id': self.tarde.id, 'cantidad': 2},
                    {'franja_id': self.noche.id, 'cantidad': 0},
                    {'franja_id': self.madrugada.id, 'cantidad': 1},
                ],
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta_rechazada.status_code, 400)
        self.assertFalse(
            AsignacionSemanal.objects.filter(
                lunes=self.lunes, franja=self.noche, cantidad=0
            ).exists()
        )

class EdicionHorarioManualTests(TestCase):
    def setUp(self):
        self.rol = Rol.objects.create(nombre='Técnico', horas_por_dia=7)
        self.franja = Franja.objects.create(
            rol=self.rol, nombre='Mañana', hora_inicio='06:00'
        )
        self.empleado = Empleado.objects.create(
            nombre='Técnico editable', rol=self.rol, franja=self.franja
        )
        self.lunes = date(2026, 10, 19)
        self.admin = User.objects.create_user(
            username='admin-edicion', password='password', is_staff=True
        )
        self.client.force_login(self.admin)
        generar_semana(self.lunes)

    def test_mueve_descanso_de_viernes_a_otro_dia_con_cuatro_permisos_y_conserva_turno(self):
        self.franja.minimo_personas = 0
        self.franja.save(update_fields=['minimo_personas'])
        Novedad.objects.create(
            empleado=self.empleado,
            tipo='PERMISO',
            fecha_inicio=self.lunes,
            fecha_fin=self.lunes + timedelta(days=3),
        )
        generar_semana(self.lunes)
        viernes = self.lunes + timedelta(days=4)
        sabado = self.lunes + timedelta(days=5)
        turno_viernes = Turno.objects.get(
            empleado=self.empleado, fecha=viernes
        )
        self.assertTrue(turno_viernes.descanso)

        respuesta = self.client.post(
            '/api/turnos/descanso/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': sabado.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        turno_viernes.refresh_from_db()
        turno_sabado = Turno.objects.get(
            empleado=self.empleado, fecha=sabado
        )
        self.assertFalse(turno_viernes.descanso)
        self.assertEqual(turno_viernes.inicio.isoformat(), '06:00:00')
        self.assertEqual(turno_viernes.fin.isoformat(), '13:00:00')
        self.assertTrue(turno_sabado.descanso)
        for dia in range(4):
            permiso = Turno.objects.get(
                empleado=self.empleado, fecha=self.lunes + timedelta(days=dia)
            )
            self.assertEqual(permiso.novedad, 'PERMISO')

        generar_semana(self.lunes)
        turno_viernes.refresh_from_db()
        turno_sabado.refresh_from_db()
        self.assertFalse(turno_viernes.descanso)
        self.assertTrue(turno_sabado.descanso)

    def test_mueve_descanso_a_dia_de_permiso_y_reemplaza_solo_ese_dia(self):
        self.franja.minimo_personas = 0
        self.franja.save(update_fields=['minimo_personas'])
        Novedad.objects.create(
            empleado=self.empleado,
            tipo='PERMISO',
            fecha_inicio=self.lunes,
            fecha_fin=self.lunes + timedelta(days=3),
            nota='Permiso original',
        )
        generar_semana(self.lunes)
        viernes = self.lunes + timedelta(days=4)
        martes = self.lunes + timedelta(days=1)

        respuesta = self.client.post(
            '/api/turnos/descanso/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': martes.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        turno_viernes = Turno.objects.get(
            empleado=self.empleado, fecha=viernes
        )
        turno_martes = Turno.objects.get(
            empleado=self.empleado, fecha=martes
        )
        self.assertFalse(turno_viernes.descanso)
        self.assertEqual(turno_viernes.inicio.isoformat(), '06:00:00')
        self.assertTrue(turno_viernes.manual)
        self.assertTrue(turno_martes.descanso)
        self.assertEqual(turno_martes.novedad, '')
        self.assertTrue(turno_martes.manual)

        permisos_restantes = list(Novedad.objects.filter(
            empleado=self.empleado, tipo='PERMISO'
        ).order_by('fecha_inicio'))
        self.assertEqual(
            [(n.fecha_inicio, n.fecha_fin, n.nota) for n in permisos_restantes],
            [
                (self.lunes, self.lunes, 'Permiso original'),
                (
                    self.lunes + timedelta(days=2),
                    self.lunes + timedelta(days=3),
                    'Permiso original',
                ),
            ],
        )

        generar_semana(self.lunes)
        turno_viernes.refresh_from_db()
        turno_martes.refresh_from_db()
        self.assertFalse(turno_viernes.descanso)
        self.assertTrue(turno_martes.descanso)
        self.assertEqual(turno_martes.novedad, '')

    def test_agrega_descanso_sin_mover_el_existente_y_persiste(self):
        self.franja.minimo_personas = 0
        self.franja.save(update_fields=['minimo_personas'])
        descanso_original = Turno.objects.get(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            descanso=True,
        ).fecha
        martes = self.lunes + timedelta(days=1)

        respuesta = self.client.post(
            '/api/turnos/descanso/agregar/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': martes.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        turno_original = Turno.objects.get(
            empleado=self.empleado, fecha=descanso_original
        )
        turno_martes = Turno.objects.get(
            empleado=self.empleado, fecha=martes
        )
        self.assertTrue(turno_original.descanso)
        self.assertTrue(turno_martes.descanso)
        self.assertTrue(turno_martes.manual)

        generar_semana(self.lunes)
        turno_original.refresh_from_db()
        turno_martes.refresh_from_db()
        self.assertTrue(turno_original.descanso)
        self.assertTrue(turno_martes.descanso)

    def test_agrega_descanso_en_permiso_sin_mover_descanso_existente(self):
        self.franja.minimo_personas = 0
        self.franja.save(update_fields=['minimo_personas'])
        Novedad.objects.create(
            empleado=self.empleado,
            tipo='PERMISO',
            fecha_inicio=self.lunes,
            fecha_fin=self.lunes + timedelta(days=2),
            nota='Permiso de tres días',
        )
        generar_semana(self.lunes)
        descanso_original = Turno.objects.get(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            descanso=True,
        ).fecha
        martes = self.lunes + timedelta(days=1)

        respuesta = self.client.post(
            '/api/turnos/descanso/agregar/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': martes.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        self.assertTrue(Turno.objects.get(
            empleado=self.empleado, fecha=descanso_original
        ).descanso)
        turno_martes = Turno.objects.get(
            empleado=self.empleado, fecha=martes
        )
        self.assertTrue(turno_martes.descanso)
        self.assertEqual(turno_martes.novedad, '')
        self.assertEqual(
            list(Novedad.objects.filter(
                empleado=self.empleado, tipo='PERMISO'
            ).order_by('fecha_inicio').values_list(
                'fecha_inicio', 'fecha_fin'
            )),
            [
                (self.lunes, self.lunes),
                (self.lunes + timedelta(days=2), self.lunes + timedelta(days=2)),
            ],
        )

        generar_semana(self.lunes)
        turno_martes.refresh_from_db()
        self.assertTrue(turno_martes.descanso)
        self.assertEqual(turno_martes.novedad, '')

    def test_convierte_descanso_en_laboral_sin_crear_otro_descanso(self):
        descanso_original = Turno.objects.get(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            descanso=True,
        ).fecha

        respuesta = self.client.post(
            '/api/turnos/descanso/trabajar/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': descanso_original.isoformat(),
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        turno = Turno.objects.get(
            empleado=self.empleado, fecha=descanso_original
        )
        self.assertFalse(turno.descanso)
        self.assertEqual(turno.inicio.strftime('%H:%M'), '06:00')
        self.assertEqual(turno.fin.strftime('%H:%M'), '13:00')
        self.assertTrue(turno.manual)
        self.assertTrue(turno.trabajar_sin_descanso_semanal)
        self.assertEqual(
            Turno.objects.filter(
                empleado=self.empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
                descanso=True,
            ).count(),
            0,
        )

        generar_semana(self.lunes)
        turno.refresh_from_db()
        self.assertFalse(turno.descanso)
        self.assertTrue(turno.trabajar_sin_descanso_semanal)
        self.assertEqual(
            Turno.objects.filter(
                empleado=self.empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
                descanso=True,
            ).count(),
            0,
        )

        generar_semana(self.lunes, descartar_manuales=True)
        turno.refresh_from_db()
        self.assertFalse(turno.trabajar_sin_descanso_semanal)
        self.assertEqual(
            Turno.objects.filter(
                empleado=self.empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
                descanso=True,
            ).count(),
            1,
        )

    def test_cambia_franja_del_tecnico_toda_la_semana_y_persiste(self):
        self.franja.minimo_personas = 0
        self.franja.save(update_fields=['minimo_personas'])
        tarde = Franja.objects.create(
            rol=self.rol, nombre='Tarde', hora_inicio='13:00',
            minimo_personas=0,
        )
        fecha_descanso = Turno.objects.get(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            descanso=True,
        ).fecha

        respuesta = self.client.post(
            '/api/tecnicos/franja/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': (self.lunes + timedelta(days=2)).isoformat(),
                'franja_id': tarde.id,
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        turnos = list(Turno.objects.filter(
            empleado=self.empleado,
            fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
        ))
        self.assertEqual(len(turnos), 7)
        for turno in turnos:
            self.assertEqual(turno.franja_id, tarde.id)
            self.assertTrue(turno.manual)
            if turno.fecha == fecha_descanso:
                self.assertTrue(turno.descanso)
                continue
            self.assertEqual(turno.inicio.isoformat(), '13:00:00')
            self.assertEqual(turno.fin.isoformat(), '20:00:00')

        generar_semana(self.lunes)
        self.assertEqual(
            set(Turno.objects.filter(
                empleado=self.empleado,
                fecha__range=(self.lunes, self.lunes + timedelta(days=6)),
            ).values_list('franja_id', flat=True)),
            {tarde.id},
        )

    def test_rechaza_cambiar_franja_de_otro_rol_y_no_tecnico(self):
        rol_supervisor = Rol.objects.create(nombre='Supervisor', horas_por_dia=6)
        franja_supervisor = Franja.objects.create(
            rol=rol_supervisor, nombre='Supervisor', hora_inicio='06:00'
        )

        respuesta = self.client.post(
            '/api/tecnicos/franja/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': self.lunes.isoformat(),
                'franja_id': franja_supervisor.id,
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no pertenece', respuesta.json()['error'])

    def test_cambia_inicio_calcula_fin_y_conserva_el_ajuste_al_regenerar(self):
        fecha_turno = self.lunes + timedelta(days=1)
        respuesta = self.client.post(
            '/api/turnos/horario/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': fecha_turno.isoformat(),
                'inicio': '08:30',
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        turno = Turno.objects.get(empleado=self.empleado, fecha=fecha_turno)
        self.assertEqual(turno.inicio.isoformat(), '08:30:00')
        self.assertEqual(turno.fin.isoformat(), '15:30:00')
        self.assertTrue(turno.manual)

        generar_semana(self.lunes)
        turno.refresh_from_db()
        self.assertEqual(turno.inicio.isoformat(), '08:30:00')
        self.assertEqual(turno.fin.isoformat(), '15:30:00')
        self.assertTrue(turno.manual)

    def test_rechaza_hora_invalida_y_turno_con_novedad(self):
        respuesta_invalida = self.client.post(
            '/api/turnos/horario/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': self.lunes.isoformat(),
                'inicio': '25:00',
            },
            content_type='application/json',
        )
        self.assertEqual(respuesta_invalida.status_code, 400)

        fecha_vacaciones = self.lunes + timedelta(days=1)
        Novedad.objects.create(
            empleado=self.empleado,
            tipo='VACACIONES',
            fecha_inicio=fecha_vacaciones,
            fecha_fin=fecha_vacaciones,
        )
        generar_semana(self.lunes)
        respuesta_novedad = self.client.post(
            '/api/turnos/horario/',
            data={
                'empleado_id': self.empleado.id,
                'fecha': fecha_vacaciones.isoformat(),
                'inicio': '08:30',
            },
            content_type='application/json',
        )
        self.assertEqual(respuesta_novedad.status_code, 400)

    def test_edicion_de_turno_especial_conserva_su_duracion_de_doce_horas(self):
        rol_supervisor = Rol.objects.create(nombre='Supervisor', horas_por_dia=6)
        franja_supervisor = Franja.objects.create(
            rol=rol_supervisor, nombre='06 a 12', hora_inicio='06:00'
        )
        supervisor = Empleado.objects.create(
            nombre='Supervisor editable', rol=rol_supervisor,
            franja=franja_supervisor,
        )
        fecha_domingo = self.lunes + timedelta(days=6)
        Turno.objects.create(
            empleado=supervisor,
            fecha=fecha_domingo,
            franja=franja_supervisor,
            inicio='06:00',
            fin='18:00',
            remoto=True,
        )

        respuesta = self.client.post(
            '/api/turnos/horario/',
            data={
                'empleado_id': supervisor.id,
                'fecha': fecha_domingo.isoformat(),
                'inicio': '07:00',
            },
            content_type='application/json',
        )

        self.assertEqual(respuesta.status_code, 200)
        turno = Turno.objects.get(empleado=supervisor, fecha=fecha_domingo)
        self.assertEqual(turno.inicio.isoformat(), '07:00:00')
        self.assertEqual(turno.fin.isoformat(), '19:00:00')
        self.assertTrue(turno.remoto)
