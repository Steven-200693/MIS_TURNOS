# MIS_TURNOS

Aplicación web para la gestión de turnos y personal, desarrollada con Django.

## Requisitos

- Python instalado.
- PowerShell en Windows (los comandos siguientes están escritos para PowerShell).

## Instalación y ejecución

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
cd C:\Users\user\MIS_TURNOS
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Cuando el servidor esté iniciado, abre [http://127.0.0.1:8000/](http://127.0.0.1:8000/) en el navegador. Para detenerlo, presiona `Ctrl+C` en PowerShell.

La aplicación utiliza SQLite. El comando `migrate` crea o actualiza la base de datos local.

## Exportación de partes

Los ZIP de partes usan la plantilla `horarios/plantillas/Plantilla Parte Trabajov2.xlsx` y conservan sus hojas auxiliares y validaciones. En cada hoja `Parte` solo se incluyen los técnicos que generan recargo nocturno ese día.

Desde la pantalla principal, un administrador puede descargar el horario semanal, un parte diario para una fecha elegida o los partes diarios de todo un período en un ZIP.

## Panel de administración

Para crear un usuario administrador, detén el servidor y ejecuta:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Después de iniciar nuevamente el servidor, entra en [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/) e inicia sesión con ese usuario.
