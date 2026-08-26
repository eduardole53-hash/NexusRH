import os
import mysql.connector
from datetime import datetime, date
from zoneinfo import ZoneInfo
from flask import Flask, redirect, render_template, request, url_for, session, flash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# Esta clave es obligatoria para usar sesiones en Flask
app.secret_key = 'nexus_secreto_2026' 

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME")
    )

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

# --- 2. RUTA DEL DASHBOARD ---
@app.route('/dashboard')
def dashboard():
    if 'usuario_id' not in session:
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # 1. Obtener datos del usuario actual
    cursor.execute("SELECT * FROM colaborador WHERE id_colaborador = %s", (session['usuario_id'],))
    usuario = cursor.fetchone()
    
    # 2. Obtener el historial de asistencia (Admin ve todos, regular ve solo los suyos)
    if session['rol'] == 'Administrador':
        cursor.execute("""
            SELECT r.*, c.nombre, c.apellido 
            FROM registro_asistencia r
            JOIN colaborador c ON r.id_colaborador = c.id_colaborador
            ORDER BY r.fecha DESC, r.hora_entrada DESC
        """)
    else:
        cursor.execute("""
            SELECT r.*, c.nombre, c.apellido 
            FROM registro_asistencia r
            JOIN colaborador c ON r.id_colaborador = c.id_colaborador
            WHERE r.id_colaborador = %s
            ORDER BY r.fecha DESC, r.hora_entrada DESC
        """, (session['usuario_id'],))
        
    historial = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', usuario=usuario, historial=historial)

# --- 3. RUTAS DE ASISTENCIA ---
@app.route('/marcar-asistencia', methods=['POST'])
def marcar_asistencia():
    id_colaborador = request.form['id_colaborador']
    zona_panama = ZoneInfo("America/Panama")
    ahora_en_panama = datetime.now(zona_panama)
    
    hoy = ahora_en_panama.date()
    hora_actual = ahora_en_panama.time()

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT * FROM registro_asistencia WHERE id_colaborador = %s AND fecha = %s", (id_colaborador, hoy))
    registro = cursor.fetchone()

    if not registro:
        cursor.execute("""
            INSERT INTO registro_asistencia (id_colaborador, fecha, hora_entrada, estado)
            VALUES (%s, %s, %s, 'Regular')
        """, (id_colaborador, hoy, hora_actual))
        flash(f"✅ Entrada registrada exitosamente a las {hora_actual.strftime('%H:%M:%S')}", "success")
    elif registro and registro['hora_salida'] is None:
        cursor.execute("UPDATE registro_asistencia SET hora_salida = %s WHERE id_registro = %s", (hora_actual, registro['id_registro']))
        flash(f"🚪 Salida registrada exitosamente a las {hora_actual.strftime('%H:%M:%S')}", "info")
    else:
        flash("⚠️ Ya has completado tu marcaje de entrada y salida para el día de hoy.", "warning")

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('dashboard'))

# --- 4. RUTAS DE ADMINISTRACIÓN (EDITAR/ELIMINAR) ---
@app.route('/editar-asistencia/<int:id_registro>', methods=['POST'])
def editar_asistencia(id_registro):
    if session.get('rol') != 'Administrador':
        return redirect(url_for('dashboard'))
        
    hora_entrada = request.form['hora_entrada']
    hora_salida = request.form.get('hora_salida')
    hora_salida = None if not hora_salida else hora_salida

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE registro_asistencia SET hora_entrada = %s, hora_salida = %s WHERE id_registro = %s", 
                   (hora_entrada, hora_salida, id_registro))
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Registro actualizado correctamente.", "success")
    return redirect(url_for('dashboard'))

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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    