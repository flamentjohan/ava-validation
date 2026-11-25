"""Demarrage de l'application AVA et ouverture automatique du navigateur."""
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

HOST, PORT = "127.0.0.1", 5000
URL = f"http://{HOST}:{PORT}"

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


def open_browser_when_ready():
    for _ in range(90):
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                webbrowser.open(URL)
                return
        except OSError:
            time.sleep(1)


def main():
    if os.path.exists("ava.log"):
        os.remove("ava.log")
    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    from app import app

    print("=" * 60)
    print("  Application AVA en cours de demarrage...")
    print("  Le premier lancement peut prendre 15 a 30 secondes.")
    print()
    print(f"  Des que la ligne 'Running on {URL}' apparait,")
    print("  ouvrez votre navigateur et allez sur :")
    print()
    print(f"        {URL}/test")
    print()
    print("  (si le navigateur ne s'ouvre pas tout seul, tapez")
    print("   cette adresse manuellement dans Chrome ou Edge)")
    print()
    print("  Pour arreter l'application : fermez cette fenetre.")
    print("=" * 60)

    app.run(host=HOST, port=PORT)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        with open("ava.log", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print("ERREUR de demarrage, detail enregistre dans ava.log :")
        print(traceback.format_exc())
