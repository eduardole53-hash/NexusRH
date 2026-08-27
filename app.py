import os
import mysql.connector
from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Flask, redirect, render_template, request, url_for, session, flash
from dotenv import load_dotenv
import json

import csv
from io import StringIO
from flask import Response

load_dotenv()

app = Flask(__name__)
# Esta clave es obligatoria para usar sesiones en Flask
app.secret_key = 'nexus_secreto_2026' 

def get_db_connection():
    conn = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='nexus_rh'
    )
    cursor = conn.cursor()
    cursor.execute("SET time_zone = '-05:00';")
    cursor.close()
    return conn

# --- 1. RUTAS DE AUTENTICACIÓN ---
@app.route('/')
def index():
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    correo = request.form['correo']
    contrasena = request.form['contrasena']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM colaborador WHERE correo_laboral = %s AND contrasena = %s", (correo, contrasena))
    usuario = cursor.fetchone()
    cursor.close()
    conn.close()

    if usuario:
        # Guardamos los datos importantes en la sesión
        session['usuario_id'] = usuario['id_colaborador']
        session['rol'] = usuario['rol']
        session['nombre'] = usuario['nombre']
        session['apellido'] = usuario['apellido']
        return redirect(url_for('dashboard'))
    else:
        return render_template('index.html', error="Credenciales incorrectas. Intenta de nuevo.")

@app.route('/logout')
def logout():
    session.clear() # Cierra la sesión
    return redirect(url_for('index'))

# --- RUTA DE MARCAJE RÁPIDO Y DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    usuario_id = session.get('usuario_id')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Métricas de tarjetas superiores
    cursor.execute("SELECT COUNT(*) AS total FROM colaborador")
    total_colaboradores = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS total FROM departamento")
    total_departamentos = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS total FROM solicitud_permiso WHERE estado = 'Pendiente'")
    total_pendientes = cursor.fetchone()['total']

    cursor.execute("SELECT COUNT(*) AS total FROM registro_asistencia WHERE fecha = CURDATE()")
    asistencias_hoy = cursor.fetchone()['total']

    # 2. Marcaje del usuario actual el día de hoy
    cursor.execute("""
        SELECT * FROM registro_asistencia 
        WHERE id_colaborador = %s AND fecha = CURDATE() 
        ORDER BY id_registro DESC LIMIT 1
    """, (usuario_id,))
    mi_marcaje_hoy = cursor.fetchone()

    # 3. Lista de quiénes han marcado hoy (Últimos 5 registros)
    cursor.execute("""
        SELECT a.*, c.nombre, c.apellido, d.nombre AS departamento
        FROM registro_asistencia a
        JOIN colaborador c ON a.id_colaborador = c.id_colaborador
        LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
        WHERE a.fecha = CURDATE()
        ORDER BY a.id_registro DESC LIMIT 5
    """)
    marcajes_recientes = cursor.fetchall()

    # 4. Datos para los gráficos compactos
    cursor.execute("""
        SELECT COALESCE(d.nombre, 'Sin Depto') AS departamento, COUNT(c.id_colaborador) AS total
        FROM colaborador c
        LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
        GROUP BY d.nombre
    """)
    dept_data = cursor.fetchall()
    labels_dept = [row['departamento'] for row in dept_data]
    values_dept = [row['total'] for row in dept_data]

    cursor.execute("SELECT estado, COUNT(*) AS total FROM solicitud_permiso GROUP BY estado")
    permisos_data = cursor.fetchall()
    labels_permisos = [row['estado'] for row in permisos_data]
    values_permisos = [row['total'] for row in permisos_data]

    cursor.close()
    conn.close()

    # Se envían las listas nativas SIN json.dumps()
    return render_template(
        'dashboard.html',
        total_colaboradores=total_colaboradores,
        total_departamentos=total_departamentos,
        total_pendientes=total_pendientes,
        asistencias_hoy=asistencias_hoy,
        mi_marcaje_hoy=mi_marcaje_hoy,
        marcajes_recientes=marcajes_recientes,
        labels_dept=labels_dept,
        values_dept=values_dept,
        labels_permisos=labels_permisos,
        values_permisos=values_permisos
    )


@app.route('/marcar-asistencia', methods=['POST'])
def marcar_asistencia():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión.", "warning")
        return redirect(url_for('index'))

    usuario_id = session.get('usuario_id')
    accion = request.form.get('accion')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT * FROM registro_asistencia WHERE id_colaborador = %s AND fecha = CURDATE() ORDER BY id_registro DESC LIMIT 1", (usuario_id,))
        registro = cursor.fetchone()

        if accion == 'entrada':
            if registro and registro['hora_salida'] is None:
                flash("Ya tienes un turno de entrada activo hoy.", "warning")
            else:
                cursor.execute("""
                    INSERT INTO registro_asistencia (id_colaborador, fecha, hora_entrada, estado)
                    VALUES (%s, CURDATE(), CURTIME(), 'Presente')
                """, (usuario_id,))
                conn.commit()
                flash("⏰ ¡Entrada registrada correctamente!", "success")

        elif accion == 'salida':
            if not registro or registro['hora_salida'] is not None:
                flash("No tienes un registro de entrada pendiente de salida.", "warning")
            else:
                cursor.execute("""
                    UPDATE registro_asistencia
                    SET hora_salida = CURTIME()
                    WHERE id_registro = %s
                """, (registro['id_registro'],))
                conn.commit()
                flash("🚪 ¡Salida registrada correctamente!", "info")

    except Exception as err:
        flash(f"Error al registrar asistencia: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('dashboard'))

# --- 4. RUTAS DE ADMINISTRACIÓN (EDITAR/ELIMINAR) ---
@app.route('/editar-asistencia/<int:id_registro>', methods=['POST'])
def editar_asistencia(id_registro):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        flash("No tienes permisos para realizar esta acción.", "danger")
        return redirect(url_for('dashboard'))

    hora_entrada = request.form['hora_entrada']
    hora_salida = request.form.get('hora_salida')
    hora_salida = None if not hora_salida else hora_salida

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE registro_asistencia 
        SET hora_entrada = %s, hora_salida = %s 
        WHERE id_registro = %s
    """, (hora_entrada, hora_salida, id_registro))
    conn.commit()
    cursor.close()
    conn.close()

    flash("Marcación actualizada correctamente.", "success")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/eliminar-asistencia/<int:id_registro>', methods=['POST'])
def eliminar_asistencia(id_registro):
    if session.get('rol') != 'Administrador':
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM registro_asistencia WHERE id_registro = %s", (id_registro,))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Registro eliminado permanentemente.", "danger")
    return redirect(url_for('dashboard'))


# --- 5. RUTAS DE GESTIÓN DE COLABORADORES (CRUD) ---
@app.route('/colaboradores', methods=['GET'])
def colaboradores():
    # Verificar si el usuario ha iniciado sesión
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Obtener la lista de departamentos (EN SINGULAR)
        cursor.execute("SELECT * FROM departamento")
        departamentos = cursor.fetchall()

        # 2. Obtener la lista de cargos (EN SINGULAR)
        cursor.execute("SELECT * FROM cargo")
        cargos = cursor.fetchall()

        # 3. Obtener los colaboradores con los JOINs actualizados (EN SINGULAR)
        query = """
            SELECT c.*, d.nombre AS nombre_departamento, ca.titulo AS nombre_cargo 
            FROM colaborador c 
            LEFT JOIN departamento d ON c.id_departamento = d.id_departamento 
            LEFT JOIN cargo ca ON c.id_cargo = ca.id_cargo
        """
        cursor.execute(query)
        empleados = cursor.fetchall()

    except Exception as err:
        flash(f"Error al cargar los datos: {err}", "danger")
        empleados, departamentos, cargos = [], [], []
    finally:
        cursor.close()
        conn.close()

    # 4. Enviar todo al HTML
    return render_template('colaboradores.html', 
                           empleados=empleados, 
                           departamentos=departamentos, 
                           cargos=cargos)

@app.route('/agregar-colaborador', methods=['POST'])
def agregar_colaborador():
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    cedula = request.form['cedula']
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    correo = request.form['correo']
    contrasena = request.form['contrasena'] 
    rol = request.form['rol']
    fecha_ingreso = request.form['fecha_ingreso'] 
    salario = request.form['salario'] 
    
    #  CAMPOS OBLIGATORIOS
    estado = request.form['estado']
    id_departamento = request.form['id_departamento']
    id_cargo = request.form['id_cargo']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Añadimos los campos extra al INSERT
        cursor.execute("""
            INSERT INTO colaborador 
            (cedula, nombre, apellido, correo_laboral, contrasena, rol, fecha_ingreso, salario, estado, id_departamento, id_cargo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (cedula, nombre, apellido, correo, contrasena, rol, fecha_ingreso, salario, estado, id_departamento, id_cargo))
        conn.commit()
        flash("Colaborador agregado exitosamente al sistema.", "success")
    except mysql.connector.Error as err:
        flash(f"Error en BD al agregar: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('colaboradores'))


@app.route('/editar-colaborador/<int:id_colaborador>', methods=['POST'])
def editar_colaborador(id_colaborador):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    cedula = request.form['cedula']
    nombre = request.form['nombre']
    apellido = request.form['apellido']
    correo = request.form['correo']
    rol = request.form['rol']
    fecha_ingreso = request.form['fecha_ingreso']
    salario = request.form['salario']
    estado = request.form['estado']
    id_departamento = request.form['id_departamento']
    id_cargo = request.form['id_cargo']

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE colaborador 
            SET cedula = %s, nombre = %s, apellido = %s, correo_laboral = %s, 
                rol = %s, fecha_ingreso = %s, salario = %s, estado = %s, 
                id_departamento = %s, id_cargo = %s
            WHERE id_colaborador = %s
        """, (cedula, nombre, apellido, correo, rol, fecha_ingreso, salario, estado, id_departamento, id_cargo, id_colaborador))
        conn.commit()
        flash("Datos del colaborador actualizados correctamente.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al actualizar: {err}", "danger")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('colaboradores'))

@app.route('/eliminar-colaborador/<int:id_colaborador>', methods=['POST'])
def eliminar_colaborador(id_colaborador):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM colaborador WHERE id_colaborador = %s", (id_colaborador,))
        conn.commit()
        flash("Colaborador eliminado permanentemente.", "warning")
    except mysql.connector.Error as err:
        # Por si hay registros de asistencia ligados a este usuario
        flash("No se puede eliminar el usuario porque tiene registros asociados (ej. Asistencia).", "danger")
    finally:
        cursor.close()
        conn.close()
    
    return redirect(url_for('colaboradores'))


# --- 6. RUTAS DE GESTIÓN DE DEPARTAMENTOS (CRUD) ---

@app.route('/departamentos', methods=['GET'])
def departamentos():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    if session.get('rol') not in ['Administrador', 'RRHH']:
        flash("No tienes permisos para acceder a esta sección.", "danger")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Consulta los departamentos junto con la cantidad de colaboradores asignados
        query = """
            SELECT d.*, COUNT(c.id_colaborador) AS total_colaboradores
            FROM departamento d
            LEFT JOIN colaborador c ON d.id_departamento = c.id_departamento
            GROUP BY d.id_departamento
            ORDER BY d.nombre ASC
        """
        cursor.execute(query)
        lista_departamentos = cursor.fetchall()
    except Exception as err:
        flash(f"Error al obtener departamentos: {err}", "danger")
        lista_departamentos = []
    finally:
        cursor.close()
        conn.close()

    return render_template('departamentos.html', departamentos=lista_departamentos)


@app.route('/agregar-departamento', methods=['POST'])
def agregar_departamento():
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    nombre = request.form.get('nombre', '').strip()
    ubicacion = request.form.get('ubicacion', '').strip()

    if not nombre:
        flash("El nombre del departamento no puede estar vacío.", "warning")
        return redirect(url_for('departamentos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO departamento (nombre, ubicacion) VALUES (%s, %s)", (nombre, ubicacion))
        conn.commit()
        flash(f"Departamento '{nombre}' creado exitosamente.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al crear departamento: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('departamentos'))


@app.route('/editar-departamento/<int:id_departamento>', methods=['POST'])
def editar_departamento(id_departamento):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    nombre = request.form.get('nombre', '').strip()
    ubicacion = request.form.get('ubicacion', '').strip()

    if not nombre:
        flash("El nombre del departamento no puede estar vacío.", "warning")
        return redirect(url_for('departamentos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE departamento SET nombre = %s, ubicacion = %s WHERE id_departamento = %s", (nombre, ubicacion, id_departamento))
        conn.commit()
        flash("Departamento actualizado correctamente.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al actualizar departamento: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('departamentos'))


@app.route('/eliminar-departamento/<int:id_departamento>', methods=['POST'])
def eliminar_departamento(id_departamento):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM departamento WHERE id_departamento = %s", (id_departamento,))
        conn.commit()
        flash("Departamento eliminado exitosamente.", "warning")
    except mysql.connector.Error as err:
        # Captura error de clave foránea si hay colaboradores asignados
        flash("No se puede eliminar este departamento porque tiene colaboradores asignados.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('departamentos'))

# --- 7. RUTAS DE GESTIÓN DE CARGOS (CRUD) ---

@app.route('/cargos', methods=['GET'])
def cargos():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    if session.get('rol') not in ['Administrador', 'RRHH']:
        flash("No tienes permisos para acceder a esta sección.", "danger")
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Consultar los cargos junto con el conteo de colaboradores asignados
        query = """
            SELECT ca.*, COUNT(c.id_colaborador) AS total_colaboradores
            FROM cargo ca
            LEFT JOIN colaborador c ON ca.id_cargo = c.id_cargo
            GROUP BY ca.id_cargo
            ORDER BY ca.titulo ASC
        """
        cursor.execute(query)
        lista_cargos = cursor.fetchall()
    except Exception as err:
        flash(f"Error al obtener cargos: {err}", "danger")
        lista_cargos = []
    finally:
        cursor.close()
        conn.close()

    return render_template('cargos.html', cargos=lista_cargos)


@app.route('/agregar-cargo', methods=['POST'])
def agregar_cargo():
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    titulo = request.form.get('titulo', '').strip()

    if not titulo:
        flash("El título del cargo no puede estar vacío.", "warning")
        return redirect(url_for('cargos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO cargo (titulo) VALUES (%s)", (titulo,))
        conn.commit()
        flash(f"Cargo '{titulo}' creado exitosamente.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al crear el cargo: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('cargos'))


@app.route('/editar-cargo/<int:id_cargo>', methods=['POST'])
def editar_cargo(id_cargo):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    titulo = request.form.get('titulo', '').strip()

    if not titulo:
        flash("El título del cargo no puede estar vacío.", "warning")
        return redirect(url_for('cargos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE cargo SET titulo = %s WHERE id_cargo = %s", (titulo, id_cargo))
        conn.commit()
        flash("Cargo actualizado correctamente.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al actualizar el cargo: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('cargos'))


@app.route('/eliminar-cargo/<int:id_cargo>', methods=['POST'])
def eliminar_cargo(id_cargo):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM cargo WHERE id_cargo = %s", (id_cargo,))
        conn.commit()
        flash("Cargo eliminado exitosamente.", "warning")
    except mysql.connector.Error as err:
        flash("No se puede eliminar este cargo porque tiene colaboradores asignados.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('cargos'))

# --- 8. RUTAS DE PERMISOS Y VACACIONES ---

@app.route('/permisos', methods=['GET'])
def permisos():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    usuario_id = session.get('usuario_id')
    rol = session.get('rol')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if rol in ['Administrador', 'RRHH']:
            # Los administradores y RRHH ven todas las solicitudes de la empresa
            query = """
                SELECT p.*, c.nombre, c.apellido 
                FROM solicitud_permiso p
                JOIN colaborador c ON p.id_colaborador = c.id_colaborador
                ORDER BY p.fecha_solicitud DESC
            """
            cursor.execute(query)
        else:
            # Los colaboradores estándar solo ven sus propias solicitudes
            query = """
                SELECT p.*, c.nombre, c.apellido 
                FROM solicitud_permiso p
                JOIN colaborador c ON p.id_colaborador = c.id_colaborador
                WHERE p.id_colaborador = %s
                ORDER BY p.fecha_solicitud DESC
            """
            cursor.execute(query, (usuario_id,))

        solicitudes = cursor.fetchall()
    except Exception as err:
        flash(f"Error al cargar las solicitudes: {err}", "danger")
        solicitudes = []
    finally:
        cursor.close()
        conn.close()

    return render_template('permisos.html', solicitudes=solicitudes)


@app.route('/solicitar-permiso', methods=['POST'])
def solicitar_permiso():
    if 'usuario_id' not in session:
        return redirect(url_for('index'))

    id_colaborador = session.get('usuario_id')
    tipo_permiso = request.form.get('tipo_permiso')
    fecha_inicio = request.form.get('fecha_inicio')
    fecha_fin = request.form.get('fecha_fin')
    motivo = request.form.get('motivo', '').strip()

    if not tipo_permiso or not fecha_inicio or not fecha_fin:
        flash("Todos los campos obligatorios deben ser completados.", "warning")
        return redirect(url_for('permisos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = """
            INSERT INTO solicitud_permiso (id_colaborador, tipo_permiso, fecha_inicio, fecha_fin, motivo)
            VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(query, (id_colaborador, tipo_permiso, fecha_inicio, fecha_fin, motivo))
        conn.commit()
        flash("Solicitud registrada exitosamente. Pendiente de aprobación.", "success")
    except mysql.connector.Error as err:
        flash(f"Error al registrar la solicitud: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('permisos'))


@app.route('/cambiar-estado-permiso/<int:id_solicitud>/<string:nuevo_estado>', methods=['POST'])
def cambiar_estado_permiso(id_solicitud, nuevo_estado):
    if session.get('rol') not in ['Administrador', 'RRHH']:
        flash("No tienes permisos para realizar esta acción.", "danger")
        return redirect(url_for('dashboard'))

    if nuevo_estado not in ['Aprobado', 'Rechazado']:
        flash("Estado inválido.", "warning")
        return redirect(url_for('permisos'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE solicitud_permiso SET estado = %s WHERE id_solicitud = %s", (nuevo_estado, id_solicitud))
        conn.commit()
        flash(f"La solicitud #{id_solicitud} ha sido cambiada a '{nuevo_estado}'.", "info")
    except mysql.connector.Error as err:
        flash(f"Error al actualizar el estado: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('permisos'))

# --- 9. RUTAS DE REPORTES Y EXPORTACIÓN ---

@app.route('/reportes', methods=['GET'])
def reportes():
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    if session.get('rol') not in ['Administrador', 'RRHH']:
        flash("No tienes permisos para acceder a esta sección.", "danger")
        return redirect(url_for('dashboard'))

    tipo_reporte = request.args.get('tipo_reporte', 'asistencia')
    fecha_inicio = request.args.get('fecha_inicio', '')
    fecha_fin = request.args.get('fecha_fin', '')
    id_departamento = request.args.get('id_departamento', '')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    datos_reporte = []
    lista_departamentos = []

    try:
        cursor.execute("SELECT * FROM departamento ORDER BY nombre ASC")
        lista_departamentos = cursor.fetchall()

        # 1. Reporte de Asistencia
        if tipo_reporte == 'asistencia':
            query = """
                SELECT a.*, c.nombre, c.apellido, d.nombre AS departamento
                FROM registro_asistencia a
                JOIN colaborador c ON a.id_colaborador = c.id_colaborador
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                WHERE 1=1
            """
            params = []
            if fecha_inicio:
                query += " AND a.fecha >= %s"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND a.fecha <= %s"
                params.append(fecha_fin)
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)

            query += " ORDER BY a.fecha DESC, a.hora_entrada DESC"
            cursor.execute(query, tuple(params))
            datos_reporte = cursor.fetchall()

        # 2. Reporte de Colaboradores
        elif tipo_reporte == 'colaboradores':
            query = """
                SELECT c.*, d.nombre AS departamento, ca.titulo AS cargo
                FROM colaborador c
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                LEFT JOIN cargo ca ON c.id_cargo = ca.id_cargo
                WHERE 1=1
            """
            params = []
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)

            query += " ORDER BY c.nombre ASC"
            cursor.execute(query, tuple(params))
            datos_reporte = cursor.fetchall()

        # 3. Reporte de Permisos / Vacaciones
        elif tipo_reporte == 'permisos':
            query = """
                SELECT p.*, c.nombre, c.apellido, d.nombre AS departamento
                FROM solicitud_permiso p
                JOIN colaborador c ON p.id_colaborador = c.id_colaborador
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                WHERE 1=1
            """
            params = []
            if fecha_inicio:
                query += " AND p.fecha_inicio >= %s"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND p.fecha_fin <= %s"
                params.append(fecha_fin)
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)

            query += " ORDER BY p.fecha_solicitud DESC"
            cursor.execute(query, tuple(params))
            datos_reporte = cursor.fetchall()

    except Exception as err:
        flash(f"Error al generar el reporte: {err}", "danger")
    finally:
        cursor.close()
        conn.close()

    return render_template(
        'reportes.html',
        datos=datos_reporte,
        departamentos=lista_departamentos,
        tipo_reporte=tipo_reporte,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        id_departamento=id_departamento
    )


@app.route('/exportar-csv', methods=['GET'])
def exportar_csv():
    if session.get('rol') not in ['Administrador', 'RRHH']:
        return redirect(url_for('dashboard'))

    tipo_reporte = request.args.get('tipo_reporte', 'asistencia')
    fecha_inicio = request.args.get('fecha_inicio', '')
    fecha_fin = request.args.get('fecha_fin', '')
    id_departamento = request.args.get('id_departamento', '')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    si = StringIO()
    writer = csv.writer(si)

    try:
        if tipo_reporte == 'asistencia':
            writer.writerow(['ID', 'Colaborador', 'Departamento', 'Fecha', 'Hora Entrada', 'Hora Salida', 'Horas Extra', 'Estado'])
            query = """
                SELECT a.id_registro, c.nombre, c.apellido, d.nombre AS departamento, a.fecha, a.hora_entrada, a.hora_salida, a.horas_extra, a.estado
                FROM registro_asistencia a
                JOIN colaborador c ON a.id_colaborador = c.id_colaborador
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                WHERE 1=1
            """
            params = []
            if fecha_inicio:
                query += " AND a.fecha >= %s"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND a.fecha <= %s"
                params.append(fecha_fin)
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)
            
            cursor.execute(query, tuple(params))
            for r in cursor.fetchall():
                writer.writerow([
                    r['id_registro'], 
                    f"{r['nombre']} {r['apellido']}", 
                    r['departamento'] or 'Sin Dpto', 
                    r['fecha'], 
                    r['hora_entrada'], 
                    r['hora_salida'] or 'En turno', 
                    r['horas_extra'] or 0, 
                    r['estado'] or 'N/A'
                ])

        elif tipo_reporte == 'colaboradores':
            writer.writerow(['ID', 'Cédula/DNI', 'Nombre Completo', 'Email', 'Departamento', 'Cargo', 'Salario'])
            query = """
                SELECT c.id_colaborador, c.dni, c.nombre, c.apellido, c.email, d.nombre AS departamento, ca.titulo AS cargo, c.salario
                FROM colaborador c
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                LEFT JOIN cargo ca ON c.id_cargo = ca.id_cargo
                WHERE 1=1
            """
            params = []
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)

            cursor.execute(query, tuple(params))
            for r in cursor.fetchall():
                writer.writerow([r['id_colaborador'], r['dni'], f"{r['nombre']} {r['apellido']}", r['email'], r['departamento'] or 'Sin Dpto', r['cargo'] or 'Sin Cargo', r['salario']])

        elif tipo_reporte == 'permisos':
            writer.writerow(['ID', 'Colaborador', 'Departamento', 'Tipo Permiso', 'Fecha Inicio', 'Fecha Fin', 'Estado'])
            query = """
                SELECT p.id_solicitud, c.nombre, c.apellido, d.nombre AS departamento, p.tipo_permiso, p.fecha_inicio, p.fecha_fin, p.estado
                FROM solicitud_permiso p
                JOIN colaborador c ON p.id_colaborador = c.id_colaborador
                LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
                WHERE 1=1
            """
            params = []
            if fecha_inicio:
                query += " AND p.fecha_inicio >= %s"
                params.append(fecha_inicio)
            if fecha_fin:
                query += " AND p.fecha_fin <= %s"
                params.append(fecha_fin)
            if id_departamento:
                query += " AND c.id_departamento = %s"
                params.append(id_departamento)

            cursor.execute(query, tuple(params))
            for r in cursor.fetchall():
                writer.writerow([r['id_solicitud'], f"{r['nombre']} {r['apellido']}", r['departamento'] or 'Sin Dpto', r['tipo_permiso'], r['fecha_inicio'], r['fecha_fin'], r['estado']])

        output = Response(si.getvalue(), mimetype="text/csv")
        output.headers["Content-Disposition"] = f"attachment; filename=reporte_{tipo_reporte}.csv"
        return output

    except Exception as err:
        flash(f"Error al exportar archivo: {err}", "danger")
        return redirect(url_for('reportes'))
    finally:
        cursor.close()
        conn.close()

@app.route('/colaborador/<int:id_colaborador>/asistencias')
def historial_colaborador(id_colaborador):
    if 'usuario_id' not in session:
        flash("Por favor inicia sesión primero.", "warning")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1. Obtener información detallada del colaborador
        cursor.execute("""
            SELECT 
                c.*, 
                d.nombre AS nombre_departamento, 
                ca.titulo AS nombre_cargo
            FROM colaborador c
            LEFT JOIN departamento d ON c.id_departamento = d.id_departamento
            LEFT JOIN cargo ca ON c.id_cargo = ca.id_cargo
            WHERE c.id_colaborador = %s
        """, (id_colaborador,))
        colaborador = cursor.fetchone()

        # 2. Obtener historial de marcajes de asistencia
        cursor.execute("""
            SELECT * 
            FROM registro_asistencia 
            WHERE id_colaborador = %s 
            ORDER BY fecha DESC, hora_entrada DESC
        """, (id_colaborador,))
        asistencias = cursor.fetchall()

    except Exception as err:
        flash(f"Error al obtener el historial de asistencias: {err}", "danger")
        colaborador = None
        asistencias = []
    finally:
        cursor.close()
        conn.close()

    return render_template('asistencias_colaborador.html', colaborador=colaborador, asistencias=asistencias)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    