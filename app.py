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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
    