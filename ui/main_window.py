"""
ui/main_window.py
MainWindow: wires together VLC playback, playlist, visualisations,
file browser, settings, equalizer, and keyboard shortcuts.
"""

from __future__ import annotations

import json
import os
import sys
import re
import random
import numpy as np
import vlc
from PyQt6.QtCore    import QDir, QModelIndex, Qt, QTimer, QSize
from PyQt6.QtGui     import QColor, QFont, QKeySequence, QPixmap, QShortcut, QIcon, QPainter
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget,
    QTextEdit, QTreeView, QVBoxLayout, QWidget, QPushButton, 
    QLineEdit
)
from PyQt6.QtGui import QFileSystemModel

from audio.engine     import (
    SampleLoader, build_detail_text, compute_fft_frame, read_album_art, read_metadata,
)
from config.settings  import (
    DEFAULT_CONFIG, PLAYLIST_PATH,
    is_audio, load_config, save_config,
)
from ui.dialogs       import EqualizerDialog, SettingsDialog
from ui.playlist      import PlaylistWidget
from ui.style         import build_stylesheet
from ui.visualizations import (
    LissajousWidget, OscilloscopeWidget, SpectralFluxWidget,
    SpectrogramWidget, SpectrumWidget, VUMeterWidget,
)
from ui.widgets       import ClickableSlider, DropArea

ICON_MAP = {
    "Settings": "icon_settings",
    "|<":       "icon_prev",
    ">":        "icon_play",
    "||":       "icon_pause",
    "[]":       "icon_stop",
    ">|":       "icon_next",
    "Shuffle":  "icon_shuffle",
    "Repeat":   "icon_repeat",
    "Save":     "icon_save",
    "Load":     "icon_load",
    "EQ":       "icon_eq",
    "Volume":   "icon_volume",
    "Muted":    "icon_mute",
    "no_art":   "icon_no_art",

}

BASE_DIR  = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

def _natural_key(s: str):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', s)]

class MainWindow(QMainWindow):
    """Quark Audio Player — main application window."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        super().__init__()
        self._vlc = vlc.Instance("--reset-plugins-cache")
        self.setWindowTitle("Quark Audio Player v1.0")
        app_icon_path = os.path.join(ASSETS_DIR, "icon_app.png")
        if os.path.exists(app_icon_path):
            self.setWindowIcon(QIcon(app_icon_path))
        self.setMinimumSize(900, 600)
        self.resize(1_100, 680)

        self._config        = load_config()
        self._current_track = None           # int | None
        self._shuffle       = False
        self._repeat        = False
        self._shortcuts: dict[str, QShortcut] = {}

        # VLC
        self._player      = self._vlc.media_player_new()
        self._player.event_manager().event_attach(
            vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error
        )

        # Background audio sample loader
        self._loader = SampleLoader()

        # Timers
        self._timer_progress = QTimer()
        self._timer_progress.setInterval(500)
        self._timer_progress.timeout.connect(self._update_progress)

        self._timer_fft = QTimer()
        self._timer_fft.setInterval(1_000 // self._config["fps"])
        self._timer_fft.timeout.connect(self._update_fft)

        self._build_ui()
        self._apply_config()
        self._apply_shortcuts()
        self._load_playlist()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Visualisation tabs ──────────────────────────────────────
        self._viz_tabs = QTabWidget()
        self._viz_tabs.setObjectName("vizTabs")

        self._spectrum     = SpectrumWidget()
        self._spectrogram  = SpectrogramWidget()
        self._oscilloscope = OscilloscopeWidget()
        self._lissajous    = LissajousWidget()
        self._flux         = SpectralFluxWidget()
        self._vumeter      = VUMeterWidget()

        self._viz_tabs.addTab(self._spectrum,    "Spectrum")
        self._viz_tabs.addTab(self._spectrogram, "Spectrogram")
        self._viz_tabs.addTab(self._oscilloscope,"Oscilloscope")
        self._viz_tabs.addTab(self._lissajous,   "Lissajous")
        self._viz_tabs.addTab(self._flux,        "Spectral Flux")
        self._viz_tabs.addTab(self._vumeter,     "VU Meter")

        # ── Left panel: file browser ────────────────────────────────
        left_panel = QWidget()
        left_panel.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        lbl_explorer = QLabel("  File Browser")
        lbl_explorer.setObjectName("sectionLabel")
        left_layout.addWidget(lbl_explorer)

        self._root_combo = QComboBox()
        self._root_combo.addItem("Home", QDir.homePath())
        self._root_combo.addItem("Root /", "/")
        user = os.environ.get("USER", "")
        drive_icon = self.style().standardIcon(
        self.style().StandardPixmap.SP_DriveHDIcon
        )
        for base in [f"/run/media/{user}", "/mnt"]:
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    path = os.path.join(base, entry)
                    if os.path.ismount(path):
                        self._root_combo.addItem(drive_icon, entry, path)
        self._root_combo.currentIndexChanged.connect(self._change_root)
        left_layout.addWidget(self._root_combo)

        self._fs_model = QFileSystemModel()
        self._fs_model.setRootPath(QDir.homePath())
        self._file_tree = QTreeView()
        self._file_tree.setModel(self._fs_model)
        self._file_tree.setRootIndex(self._fs_model.index(QDir.homePath()))
        self._file_tree.setColumnWidth(0, 220)
        for col in [1, 2, 3]:
            self._file_tree.hideColumn(col)
        self._file_tree.setHeaderHidden(True)
        self._file_tree.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self._file_tree.doubleClicked.connect(self._on_file_double_click)
        self._file_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_tree.customContextMenuRequested.connect(self._on_file_context_menu)
        left_layout.addWidget(self._file_tree)

        # ── Right panel: playlist + detail ──────────────────────────
        right_panel = DropArea(self._on_drop)
        right_panel.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        lbl_playlist = QLabel("  Playlist")
        lbl_playlist.setObjectName("sectionLabel")
        right_layout.addWidget(lbl_playlist)

        # Search bar (hidden by default)
        self._search_bar = QWidget()
        sl = QHBoxLayout(self._search_bar)
        sl.setContentsMargins(4, 4, 4, 4)
        self._search_field = QLineEdit()
        self._search_field.setPlaceholderText("Search artist / title / album…")
        self._search_field.textChanged.connect(lambda t: self._playlist.filter(t))
        btn_close_search = QPushButton("X")
        btn_close_search.setFixedSize(24, 24)
        btn_close_search.clicked.connect(self._close_search)
        sl.addWidget(self._search_field)
        sl.addWidget(btn_close_search)
        self._search_bar.hide()
        right_layout.addWidget(self._search_bar)

        # Playlist
        self._playlist = PlaylistWidget()
        self._playlist.doubleClicked.connect(
            lambda idx: self._play_item(self._playlist.topLevelItem(idx.row()))
        )
        self._playlist.itemSelectionChanged.connect(self._on_selection_changed)

        # Tabs: playlist + metadata detail
        content_tabs = QTabWidget()
        playlist_tab = QWidget()
        pt_layout = QVBoxLayout(playlist_tab)
        pt_layout.setContentsMargins(0, 0, 0, 0)
        pt_layout.addWidget(self._playlist)
        content_tabs.addTab(playlist_tab, "Playlist")

        detail_tab = QWidget()
        dt_layout = QVBoxLayout(detail_tab)
        self._detail_text = QTextEdit()
        self._detail_text.setReadOnly(True)
        dt_layout.addWidget(self._detail_text)
        content_tabs.addTab(detail_tab, "Details")
        right_layout.addWidget(content_tabs)

        # ── Splitters ────────────────────────────────────────────────
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.addWidget(left_panel)
        h_splitter.addWidget(right_panel)
        h_splitter.setSizes([400, 700])

        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(self._viz_tabs)
        v_splitter.addWidget(h_splitter)
        v_splitter.setSizes([150, 500])
        layout.addWidget(v_splitter)

        # ── Control bar ──────────────────────────────────────────────
        control_bar = QWidget()
        control_bar.setObjectName("controlBar")
        control_bar.setFixedHeight(110)
        cb_layout = QHBoxLayout(control_bar)
        cb_layout.setContentsMargins(8, 8, 16, 8)
        cb_layout.setSpacing(12)

        self._album_art = QLabel()
        self._album_art.setFixedSize(90, 90)
        self._album_art.setObjectName("albumArt")
        self._album_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cb_layout.addWidget(self._album_art)

        ctrl_col = QVBoxLayout()
        ctrl_col.setContentsMargins(0, 0, 0, 0)
        ctrl_col.setSpacing(6)
        cb_layout.addLayout(ctrl_col)

        self._track_label = QLabel("— No track —")
        self._track_label.setObjectName("trackLabel")
        self._track_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ctrl_col.addWidget(self._track_label)

        prog_row = QHBoxLayout()
        self._progress = ClickableSlider(Qt.Orientation.Horizontal)
        self._progress.setObjectName("progressBar")
        self._progress.setRange(0, 1_000)
        self._progress.sliderMoved.connect(self._seek)
        self._progress.setFixedHeight(24)
        self._time_label = QLabel("0:00 / 0:00")
        self._time_label.setObjectName("timeLabel")
        self._time_label.setFixedWidth(90)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_row.addWidget(self._progress)
        prog_row.addWidget(self._time_label)
        ctrl_col.addLayout(prog_row)

        btn_row = QHBoxLayout()
        self._btn_settings = self._ctrl_btn("Settings", self._open_settings)
        self._btn_prev     = self._ctrl_btn("|<",       self._prev_track)
        self._btn_play     = self._ctrl_btn(">",        self._toggle_play)
        self._btn_stop     = self._ctrl_btn("[]",       self._stop)
        self._btn_next     = self._ctrl_btn(">|",       self._next_track)
        for btn in [self._btn_settings, self._btn_prev, self._btn_play,
                    self._btn_stop, self._btn_next]:
            btn_row.addWidget(btn)

        btn_row.addStretch()

        # ── Volume ──────────────────────────────────────────────────────────
        self._volume = ClickableSlider(Qt.Orientation.Horizontal)
        self._volume.setObjectName("volumeSlider")
        self._volume.setRange(0, 100)
        self._volume.setValue(80)
        self._volume.setFixedWidth(100)
        self._volume.valueChanged.connect(lambda v: self._player.audio_set_volume(v))
        self._player.audio_set_volume(80)

        self._btn_mute = self._ctrl_btn("Volume", self._toggle_mute, checkable=True)
        btn_row.addWidget(self._btn_mute)
        btn_row.addWidget(self._volume)

        self._btn_shuffle = self._ctrl_btn("Shuffle", self._toggle_shuffle, checkable=True)
        self._btn_repeat  = self._ctrl_btn("Repeat",  self._toggle_repeat,  checkable=True)
        self._btn_save    = self._ctrl_btn("Save",    self._save_playlist_as)
        self._btn_load    = self._ctrl_btn("Load",    self._load_playlist_from)
        self._btn_eq      = self._ctrl_btn("EQ",      self._open_equalizer)
        for btn in [self._btn_shuffle, self._btn_repeat,
                    self._btn_save, self._btn_load, self._btn_eq]:
            btn_row.addWidget(btn)

        ctrl_col.addLayout(btn_row)
        layout.addWidget(control_bar)

        self.statusBar().showMessage(
            "Welcome! Double-click an audio file to add it to the playlist."
        )

        self._icon_buttons: dict[str, QPushButton] = {
            "Settings": self._btn_settings,
            "|<":       self._btn_prev,
            ">":        self._btn_play,
            "[]":       self._btn_stop,
            ">|":       self._btn_next,
            "Shuffle":  self._btn_shuffle,
            "Repeat":   self._btn_repeat,
            "Save":     self._btn_save,
            "Load":     self._btn_load,
            "EQ":       self._btn_eq,
            "Volume":   self._btn_mute,
        }

        self._show_no_art()
    
    def _refresh_icons(self) -> None:
        """Retint all button icons to match the current background."""
        for label, btn in self._icon_buttons.items():
            icon_name = ICON_MAP.get(label, "")
            icon_path = os.path.join(ASSETS_DIR, f"{icon_name}.png")
            if os.path.exists(icon_path):
                btn.setIcon(self._load_icon(icon_name))
        # play button may currently show pause icon
        self._set_play_icon(self._player.is_playing())
        # mute button may currently show muted icon
        if self._btn_mute.isChecked():
            self._btn_mute.setIcon(self._load_icon(ICON_MAP["Muted"]))

    # ------------------------------------------------------------------
    # Button factory
    # ------------------------------------------------------------------

    def _load_icon(self, name: str) -> QIcon:
        """Load an icon and tint it to contrast with the current background."""
        path = os.path.join(ASSETS_DIR, f"{name}.png")
        if not os.path.exists(path):
            return QIcon()
        
        px = QPixmap(path)
        
        # Determine if background is dark or light
        bg = QColor(self._config["background_color"])
        luminance = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
        tint = QColor("#1a1a2e") if luminance > 128 else QColor("#ffffff")
        
        # Apply tint via painter composition
        tinted = QPixmap(px.size())
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, px)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), tint)
        painter.end()
        
        return QIcon(tinted)

    def _ctrl_btn(self, label, slot, checkable=False):
        btn = QPushButton()
        btn.setObjectName("controlButton")
        btn.setFixedSize(54, 36)
        btn.setCheckable(checkable)
        btn.clicked.connect(slot)
        icon_path = os.path.join(ASSETS_DIR, f"{ICON_MAP.get(label, '')}.png")
        if os.path.exists(icon_path):
            btn.setIcon(self._load_icon(ICON_MAP.get(label, '')))
            btn.setIconSize(QSize(22, 22))
        else:
            btn.setText(label)   # fallback
        return btn

    # ------------------------------------------------------------------
    # Config / style
    # ------------------------------------------------------------------

    def _apply_config(self) -> None:
        fps = self._config["fps"]
        self._timer_fft.setInterval(1_000 // fps)
        self._flux.set_max_points(self._config.get("flux_history", 2000))
        self._spectrogram.set_max_cols(self._config.get("max_cols", 200))
        cp = self._config["primary_color"]
        ca = self._config["accent_color"]
        for w in [self._spectrum, self._oscilloscope, self._lissajous,
                self._flux, self._vumeter]:
            w.set_colors(cp, ca)
        self.setStyleSheet(build_stylesheet(self._config))
        # guard: _icon_buttons doesn't exist yet on first call from __init__
        if hasattr(self, "_icon_buttons"):
            self._refresh_icons()

    def _apply_shortcuts(self) -> None:
        for sc in self._shortcuts.values():
            sc.setEnabled(False)
        self._shortcuts.clear()
        mapping = {
            "play_pause": self._toggle_play,
            "next":       self._next_track,
            "previous":   self._prev_track,
        }
        shortcuts = self._config.get("shortcuts", DEFAULT_CONFIG["shortcuts"])
        for key, slot in mapping.items():
            seq = shortcuts.get(key, DEFAULT_CONFIG["shortcuts"][key])
            sc  = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(slot)
            self._shortcuts[key] = sc

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config = dlg.config
            self._apply_config()
            self._apply_shortcuts()
            save_config(self._config)

    # ------------------------------------------------------------------
    # File browser
    # ------------------------------------------------------------------

    def _change_root(self, index: int) -> None:
        path = self._root_combo.itemData(index)
        self._fs_model.setRootPath(path)
        self._file_tree.setRootIndex(self._fs_model.index(path))

    def _on_file_double_click(self, index: QModelIndex) -> None:
        path = self._fs_model.filePath(index)
        if os.path.isfile(path) and is_audio(path):
            self._add_file(path)
            self.statusBar().showMessage(f"Added: {os.path.basename(path)}")

    def _on_file_context_menu(self, position) -> None:
        index = self._file_tree.indexAt(position)
        if not index.isValid():
            return
        path = self._fs_model.filePath(index)
        if os.path.isdir(path):
            from PyQt6.QtWidgets import QMenu
            menu = QMenu(self)
            action = menu.addAction("Add folder to playlist")
            action.triggered.connect(lambda: self._add_folder(path))
            menu.exec(self._file_tree.viewport().mapToGlobal(position))

    def _add_folder(self, folder: str) -> None:
        count = 0
        for name in sorted(os.listdir(folder), key=_natural_key):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and is_audio(full):
                self._add_file(full)
                count += 1

    def _add_file(self, path: str) -> None:
        meta = read_metadata(path)
        self._playlist.add_track(
            path,
            meta["track"],
            meta["artist"],
            meta["album"],
            meta["title"],
            meta["duration_str"],
        )

    # ------------------------------------------------------------------
    # Drag-and-drop
    # ------------------------------------------------------------------

    def _on_drop(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if os.path.isfile(path) and is_audio(path):
                self._add_file(path)
            elif os.path.isdir(path):
                self._add_folder(path)
        event.accept()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _close_search(self) -> None:
        self._search_bar.hide()
        self._search_field.clear()
        self._playlist.clear_filter()

    # ------------------------------------------------------------------
    # Playlist persistence
    # ------------------------------------------------------------------

    def _load_playlist(self) -> None:
        if not os.path.exists(PLAYLIST_PATH):
            return
        try:
            with open(PLAYLIST_PATH) as f:
                data = json.load(f)
            self._playlist.from_list(data, replace=True)
        except Exception as e:
            print(f"[Playlist] Cannot load: {e}")

    def _save_playlist(self) -> None:
        try:
            with open(PLAYLIST_PATH, "w") as f:
                json.dump(self._playlist.to_list(), f, indent=2)
        except Exception as e:
            print(f"[Playlist] Cannot save: {e}")

    def _save_playlist_as(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save playlist",
            os.path.expanduser("~/playlist.json"),
            "JSON playlists (*.json)",
        )
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump(self._playlist.to_list(), f, indent=2)
            self.statusBar().showMessage(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")

    def _load_playlist_from(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load playlist",
            os.path.expanduser("~"),
            "JSON playlists (*.json)",
        )
        if not path:
            return
        choice = QMessageBox.question(
            self, "Load playlist",
            "Replace current playlist or append?",
            QMessageBox.StandardButton.Reset    # Replace
            | QMessageBox.StandardButton.Yes    # Append
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return
        replace = (choice == QMessageBox.StandardButton.Reset)
        try:
            with open(path) as f:
                data = json.load(f)
            count = self._playlist.from_list(data, replace=replace)
            self.statusBar().showMessage(f"{count} tracks loaded from {os.path.basename(path)}")
        except Exception as e:
            self.statusBar().showMessage(f"Error: {e}")

    # ------------------------------------------------------------------
    # Metadata / album art display
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        items = self._playlist.selectedItems()
        if items:
            self._detail_text.setText(
                build_detail_text(self._playlist.path_of(items[0]))
            )

    def _update_album_art(self, path: str) -> None:
        data = read_album_art(path)
        if data:
            px = QPixmap()
            px.loadFromData(data)
            if not px.isNull():
                px = px.scaled(90, 90,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
                self._album_art.setPixmap(px)
                self._album_art.setText("")
                return
        self._show_no_art()

    def _show_no_art(self) -> None:
        no_art_path = os.path.join(ASSETS_DIR, "icon_no_art.png")
        if os.path.exists(no_art_path):
            px = QPixmap(no_art_path)
            if not px.isNull():
                # Convert black background to transparent
                img = px.toImage()
                img = img.convertToFormat(img.Format.Format_ARGB32)
                for y in range(img.height()):
                    for x in range(img.width()):
                        color = QColor(img.pixel(x, y))
                        # If the pixel is dark enough, make it transparent
                        if color.red() < 30 and color.green() < 30 and color.blue() < 30:
                            img.setPixel(x, y, 0x00000000)
                px = QPixmap.fromImage(img)
                px = px.scaled(90, 90,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
                self._album_art.setPixmap(px)
                self._album_art.setText("")
                return
        self._album_art.setPixmap(QPixmap())
        self._album_art.setText("[no art]")

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
        
    def _set_play_icon(self, playing: bool) -> None:
        label = "||" if playing else ">"
        icon_path = os.path.join(ASSETS_DIR, f"{ICON_MAP[label]}.png")
        if os.path.exists(icon_path):
            self._btn_play.setIcon(self._load_icon(ICON_MAP[label]))
        else:
            self._btn_play.setText(label)


    def _play_item(self, item) -> None:
        if item is None:
            return
        path = self._playlist.path_of(item)
        if not os.path.exists(path):
            self.statusBar().showMessage(f"File not found: {path}")
            return
        if not os.access(path, os.R_OK):
            self.statusBar().showMessage(f"Permission denied: {os.path.basename(path)}")
            return

        media = self._vlc.media_new(path)
        if media is None:
            self.statusBar().showMessage("VLC could not create media object.")
            return

        self._player.set_media(media)
        if self._player.play() == -1:
            self.statusBar().showMessage("VLC refused to play this file.")
            return

        self._current_track = self._playlist.indexOfTopLevelItem(item)
        self._playlist.setCurrentItem(item)

        meta = read_metadata(path)
        artist, title = meta["artist"], meta["title"]
        self._track_label.setText(f"  {artist} — {title}")
        self._update_album_art(path)
        self._set_play_icon(True)
        self._detail_text.setText(build_detail_text(path))

        # Status bar: bitrate + sample rate if available
        br, sr = meta["bitrate"], meta["sample_rate"]
        extra  = f" | {br} @ {sr}" if br and sr else ""
        self.statusBar().showMessage(f"Playing: {artist} — {title}{extra}")

        self._timer_progress.start()
        self._timer_fft.start()
        self._loader.load(path)
    
    def _toggle_play(self) -> None:
        if self._player.is_playing():
            self._player.pause()
            self._set_play_icon(False)
            self._timer_progress.stop()
            self._timer_fft.stop()
        else:
            if self._current_track is None and self._playlist.topLevelItemCount() > 0:
                self._play_item(self._playlist.topLevelItem(0))
            else:
                self._player.play()
                self._set_play_icon(True)
                self._timer_progress.start()
                self._timer_fft.start()

    def _toggle_mute(self) -> None:
        if self._btn_mute.isChecked():
            self._volume_before_mute = self._player.audio_get_volume()
            self._player.audio_set_volume(0)
            icon_name = ICON_MAP["Muted"]
            if os.path.exists(os.path.join(ASSETS_DIR, f"{icon_name}.png")):
                self._btn_mute.setIcon(self._load_icon(icon_name))
            else:
                self._btn_mute.setText("Muted")
        else:
            self._player.audio_set_volume(getattr(self, "_volume_before_mute", 80))
            self._volume.setValue(self._player.audio_get_volume())
            icon_name = ICON_MAP["Volume"]
            if os.path.exists(os.path.join(ASSETS_DIR, f"{icon_name}.png")):
                self._btn_mute.setIcon(self._load_icon(icon_name))
            else:
                self._btn_mute.setText("Volume")

    def _stop(self) -> None:
        self._player.stop()
        self._set_play_icon(False)
        self._progress.setValue(0)
        self._timer_progress.stop()
        self._timer_fft.stop()
        self.statusBar().showMessage("Stopped.")

    def _next_track(self) -> None:
        if self._current_track is None:
            return
        if self._repeat:
            self._play_item(self._playlist.item_at_row(self._current_track))
            return
        nxt = (random.randint(0, self._playlist.topLevelItemCount() - 1)
               if self._shuffle
               else self._current_track + 1)
        item = self._playlist.item_at_row(nxt)
        if item:
            self._play_item(item)
        else:
            self._timer_fft.stop()
            self._timer_progress.stop()
            self._set_play_icon(False)
            self.statusBar().showMessage("End of playlist.")

    def _prev_track(self) -> None:
        if self._current_track is None or self._current_track == 0:
            return
        self._play_item(self._playlist.item_at_row(self._current_track - 1))

    def _toggle_shuffle(self) -> None:
        self._shuffle = self._btn_shuffle.isChecked()

    def _toggle_repeat(self) -> None:
        self._repeat = self._btn_repeat.isChecked()

    def _seek(self, value: int) -> None:
        self._player.set_position(value / 1_000.0)

    # ------------------------------------------------------------------
    # Progress timer
    # ------------------------------------------------------------------

    def _update_progress(self) -> None:
        if self._player.get_state() == vlc.State.Ended:
            self._next_track()
            return
        total = self._player.get_length()
        if total > 0:
            self._progress.setValue(int(self._player.get_position() * 1_000))
            cur = self._player.get_time()
            self._time_label.setText(
                f"{self._ms_to_str(cur)} / {self._ms_to_str(total)}"
            )

    @staticmethod
    def _ms_to_str(ms: int) -> str:
        s = max(0, ms // 1_000)
        return f"{s // 60}:{s % 60:02d}"

    # ------------------------------------------------------------------
    # FFT timer
    # ------------------------------------------------------------------

    def _update_fft(self) -> None:
        samples = self._loader.samples
        if samples is None:
            return
        pos = self._player.get_position()
        try:
            frame = compute_fft_frame(samples, pos, self._config["bar_count"])
        except Exception as e:
            print(f"[FFT] {e}")
            return
        if frame is None:
            return

        self._spectrum.set_bars(frame["bars"])
        self._spectrogram.add_column(frame["bars"])
        self._oscilloscope.set_samples(frame["mono"])
        self._lissajous.set_samples(frame["left"], frame["right"])
        self._flux.update_spectrum(frame["bars"])

        lv = float(np.abs(np.array(frame["left"])).mean())
        rv = float(np.abs(np.array(frame["right"])).mean())
        self._vumeter.set_levels(min(1.0, lv), min(1.0, rv))

    # ------------------------------------------------------------------
    # Equalizer
    # ------------------------------------------------------------------

    def _open_equalizer(self) -> None:
        EqualizerDialog(self._player, self).exec()

    # ------------------------------------------------------------------
    # VLC error callback
    # ------------------------------------------------------------------

    def _on_vlc_error(self, _event) -> None:
        self.statusBar().showMessage("Playback error: corrupt or unsupported file.")
        self._set_play_icon(False)
        self._timer_progress.stop()
        self._timer_fft.stop()

    # ------------------------------------------------------------------
    # Keyboard events
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        rc = self._config.get("shortcuts", DEFAULT_CONFIG["shortcuts"])

        if event.key() == Qt.Key.Key_Escape and self._search_bar.isVisible():
            self._close_search()
            return

        search_seq = QKeySequence(rc.get("search", "Ctrl+F"))
        if search_seq.matches(QKeySequence(event.keyCombination())) \
                == QKeySequence.SequenceMatch.ExactMatch:
            self._search_bar.show()
            self._search_field.setFocus()
            return

        if event.key() == Qt.Key.Key_Delete:
            removed = self._playlist.remove_selected()
            if removed:
                self.statusBar().showMessage(
                    f"{removed} track(s) removed. Ctrl+Z to undo."
                )
            return

        if event.key() == Qt.Key.Key_Return and self._file_tree.hasFocus():
            for index in self._file_tree.selectedIndexes():
                path = self._fs_model.filePath(index)
                if os.path.isdir(path):
                    self._add_folder(path)
                elif is_audio(path):
                    self._add_file(path)
            return

        undo_seq = QKeySequence(rc.get("undo", "Ctrl+Z"))
        if undo_seq.matches(QKeySequence(event.keyCombination())) \
                == QKeySequence.SequenceMatch.ExactMatch:
            if self._playlist.undo_delete():
                self.statusBar().showMessage("Undo: track restored.")
            return

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._timer_fft.stop()
        self._timer_progress.stop()
        self._save_playlist()
        event.accept()
