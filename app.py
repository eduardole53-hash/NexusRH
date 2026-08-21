import os
import mysql.connector
from flask import Flask, jsonify, redirect, render_template, request, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME")
    )

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    correo = request.form['correo']
    contrasena = request.form['contrasena']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("""
        SELECT * FROM colaborador 
        WHERE correo_laboral = %s AND contrasena = %s
    """, (correo, contrasena))
    
    usuario = cursor.fetchone()
    
    cursor.close()
    conn.close()

    if usuario:
        return f"¡Bienvenido al sistema, {usuario['nombre']} {usuario['apellido']}! Tu rol es: {usuario['rol']}"
    else:
        return render_template('index.html', error="Credenciales incorrectas. Intenta de nuevo.")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)