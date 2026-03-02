"""
main.py
Entry point for Quark Audio Player.

Dependencies:
    pip install PyQt6 python-vlc soundfile mutagen
    sudo apt install vlc
"""
import vlc_setup
import os
import sys
from PyQt6.QtGui     import QIcon
from PyQt6.QtWidgets import QApplication
from ui.main_window  import MainWindow
from config.settings import is_audio
import socket
import threading

SINGLE_INSTANCE_PORT = 47847

BASE_DIR   = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

def try_send_to_existing(paths: list[str]) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", SINGLE_INSTANCE_PORT))
        for path in paths:
            sock.sendall((path + "\n").encode())
        sock.close()
        return True
    except ConnectionRefusedError:
        return False

def start_listener(window):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
    server.listen(5)
    while True:
        conn, _ = server.accept()
        data = conn.recv(4096).decode()
        conn.close()
        for path in data.strip().split("\n"):
            if path and os.path.isfile(path):
                window._socket_file_received.emit(path)

def main() -> None:
    args = sys.argv[1:]
    path_arg = " ".join(args) if args else None

    if path_arg and try_send_to_existing([path_arg]):
        return

    app = QApplication(sys.argv)
    app.setApplicationName("Quark Audio Player")
    icon_path = os.path.join(ASSETS_DIR, "icon_app.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()

    if path_arg and os.path.isfile(path_arg) and is_audio(path_arg):
        window._add_file(path_arg)
        window._play_item(window._playlist.topLevelItem(
            window._playlist.topLevelItemCount() - 1
        ))

    t = threading.Thread(target=start_listener, args=(window,), daemon=True)
    t.start()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()