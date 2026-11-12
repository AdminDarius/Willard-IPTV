#!/usr/bin/env python3
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
SERVER = BASE / "server"
APP = SERVER / "app.py"
LOG = SERVER / "startup.log"
PID = SERVER / "server.pid"

HOST = "127.0.0.1"
PORT = 8767

def is_running():
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False

def main():
    if not APP.is_file():
        print("ERRO: server/app.py não encontrado.")
        return 1

    if is_running():
        print("Servidor Willard já está ativo.")
        print(f"Endereço: http://{HOST}:{PORT}")
        return 0

    print("Iniciando servidor Willard...")

    try:
        with LOG.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(APP)],
                cwd=str(SERVER),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )

        PID.write_text(str(process.pid), encoding="utf-8")

        for _ in range(30):
            time.sleep(0.5)
            if is_running():
                print("Servidor iniciado com sucesso!")
                print(f"Endereço: http://{HOST}:{PORT}")
                print(f"Processo: {process.pid}")
                print(f"Registro: {LOG}")
                return 0

            if process.poll() is not None:
                break

        print("ERRO: o servidor não iniciou corretamente.")
        print("Confira o registro:")
        print(f"tail -n 40 {LOG}")
        return 1

    except Exception as error:
        print(f"Erro ao iniciar: {error}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
