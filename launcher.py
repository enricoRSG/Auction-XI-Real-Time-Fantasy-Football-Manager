from __future__ import annotations

import socket
import webbrowser
from threading import Timer

import uvicorn

HOST = "0.0.0.0"
PORT = 8000


def local_ip() -> str:
    """Best-effort LAN IP discovery without contacting an external service."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def open_admin_home() -> None:
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:
        pass


if __name__ == "__main__":
    ip = local_ip()
    print("\nAuction XI – Real-Time Fantasy Football Manager")
    print("=" * 28)
    print(f"Battitore su questo PC: http://127.0.0.1:{PORT}")
    if ip != "127.0.0.1":
        print(f"Dispositivi sulla stessa rete Wi-Fi/LAN: http://{ip}:{PORT}")
    else:
        print("IP di rete non rilevato automaticamente: usa l'indirizzo del PC sulla rete locale.")
    print("\nPer partecipanti realmente fuori dalla rete locale serve pubblicare l'app su Internet o usare un tunnel sicuro.")
    print("Premi CTRL+C per arrestare il server.\n")

    Timer(1.0, open_admin_home).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
