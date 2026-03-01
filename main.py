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

BASE_DIR   = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Quark Audio Player")
    icon_path = os.path.join(ASSETS_DIR, "icon_app.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()

    # Open files passed as arguments (e.g. from file manager)
    for path in sys.argv[1:]:
        if os.path.isfile(path) and is_audio(path):
            window._add_file(path)
            window._play_item(window._playlist.topLevelItem(
                window._playlist.topLevelItemCount() - 1
            ))

    sys.exit(app.exec())

if __name__ == "__main__":
    main()