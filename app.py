from flask import Flask, jsonify, render_template
import mysql.connector
import os
from dotenv import load_dotenv

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

app = Flask(__name__)

# Función para conectar a la base de datos
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME")
    )

# Ruta principal (luego aquí cargaremos el HTML del Login)
@app.route('/')
def index():
    return "¡Servidor Backend de Nexus RH Funcionando!"

# Ruta de prueba para verificar la conexión a MySQL
@app.route('/test-db')
def test_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) # Devuelve los datos como diccionarios
        
        # Consultamos el usuario administrador que creaste
        cursor.execute("""
            SELECT c.nombre, c.apellido, c.rol, d.nombre AS departamento 
            FROM colaborador c
            JOIN departamento d ON c.id_departamento = d.id_departamento
        """)
        usuarios = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({"status": "success", "data": usuarios})
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    # Ejecutamos el servidor en el puerto 5000
    app.run(debug=True, host='0.0.0.0', port=5000)