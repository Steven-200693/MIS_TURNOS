from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase

from .models import AsignacionSemanal, Empleado, Franja, Novedad, Rol, Turno
from .servicios import generar_semana


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
                    esperado = 42
                    dias_trabajados_fin_de_semana[empleado.id].append(
                        jornada.fecha.weekday()
                    )
                else:
                    self.assertTrue(descanso_sabado)
                    self.assertTrue(descanso_domingo)
                    esperado = 30
                    fines_de_semana_libres[empleado.id] += 1

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

    def test_supervisores_rotan_por_las_cuatro_franjas_cada_lunes(self):
        franjas_por_supervisor = {
            supervisor.id: set() for supervisor in self.supervisores
        }

        for numero_semana in range(4):
            lunes = self.lunes + timedelta(days=7 * numero_semana)
            generar_semana(lunes)
            franjas_semana = set()
            for supervisor in self.supervisores:
                turnos = list(Turno.objects.filter(
                    empleado=supervisor,
                    fecha__range=(lunes, lunes + timedelta(days=6)),
                ).order_by('fecha'))
                ids_franja = {turno.franja_id for turno in turnos}
                self.assertEqual(len(ids_franja), 1)
                franja_id = next(iter(ids_franja))
                franjas_semana.add(franja_id)
                franjas_por_supervisor[supervisor.id].add(franja_id)

                franja = Franja.objects.get(pk=franja_id)
                for turno in turnos[:5]:
                    if turno.novedad:
                        continue
                    self.assertEqual(turno.inicio, franja.hora_inicio)

            self.assertEqual(franjas_semana, {franja.id for franja in self.franjas})
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

        for ids_franja in franjas_por_supervisor.values():
            self.assertEqual(ids_franja, {franja.id for franja in self.franjas})


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

    def test_rechaza_cupos_sin_respaldo_minimo_de_noche(self):
        admin = User.objects.create_user(
            username='admin-cupos-invalidos', password='password', is_staff=True
        )
        self.client.force_login(admin)

        respuesta = self.client.post(
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

        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(
            AsignacionSemanal.objects.filter(lunes=self.lunes).exists()
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
