"""
ui/playlist.py
PlaylistWidget: QTreeWidget subclass managing the track list.

Sorting is O(n log n) in the Qt layer but duplicate-checking on insertion
uses a Python set for O(1) average-case lookup.
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore    import Qt

class PlaylistItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        col = self.treeWidget().sortColumn()
        if col == PlaylistWidget.COL_TRACK:
            try:
                return int(self.text(col)) < int(other.text(col))
            except ValueError:
                pass
        return self.text(col) < other.text(col)

class PlaylistWidget(QTreeWidget):
    """
    A sortable, searchable playlist with:
    - O(1) duplicate detection via a path hash-set
    - History stack for undo-delete (capped at MAX_HISTORY)
    """

    MAX_HISTORY = 100

    COLUMNS   = ["#", "Artist", "Album", "Title", "Duration"]
    COL_TRACK = 0
    COL_ARTIST = 1
    COL_ALBUM  = 2
    COL_TITLE  = 3
    COL_DUR    = 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(self.COLUMNS))
        self.setHeaderLabels(self.COLUMNS)
        self.header().setSortIndicatorShown(True)
        self.header().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(True)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        # O(1) duplicate check: maps absolute_path -> QTreeWidgetItem
        self._path_index: dict[str, PlaylistItem] = {}

        # Undo history: list of (row, track, artist, album, title, dur, path)
        self._history: list[tuple] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_track(self,path: str,track: str,artist: str,album: str,title: str,duration: str,) -> Optional[QTreeWidgetItem]:
        if path in self._path_index:
            return None

        item = PlaylistItem([track, artist, album, title, duration])
        item.setData(0, Qt.ItemDataRole.UserRole, path)

        self.addTopLevelItem(item)
        self._path_index[path] = item
        return item

    def remove_selected(self) -> int:
        """
        Remove all selected items, push them onto the undo stack.
        Returns the number of removed items.
        """
        items = self.selectedItems()
        for item in items:
            row   = self.indexOfTopLevelItem(item)
            path  = item.data(0, Qt.ItemDataRole.UserRole)
            self._history.append((
                row,
                item.text(self.COL_TRACK),
                item.text(self.COL_ARTIST),
                item.text(self.COL_ALBUM),
                item.text(self.COL_TITLE),
                item.text(self.COL_DUR),
                path,
            ))
            self.takeTopLevelItem(row)
            self._path_index.pop(path, None)  # O(1) removal from index

        # Cap history to avoid memory leak
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

        return len(items)

    def undo_delete(self) -> bool:
        """Restore the last deleted item.  Returns True on success."""
        if not self._history:
            return False
        row, track, artist, album, title, dur, path = self._history.pop()
        item = PlaylistItem([track, artist, album, title, dur])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        self.insertTopLevelItem(row, item)
        self._path_index[path] = item         # O(1) re-insert
        return True

    def clear_all(self) -> None:
        self.clear()
        self._path_index.clear()
        self._history.clear()

    def filter(self, text: str) -> None:
        """Show only items matching *text* in artist / album / title."""
        text = text.lower()
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            visible = (
                text in item.text(self.COL_ARTIST).lower()
                or text in item.text(self.COL_ALBUM).lower()
                or text in item.text(self.COL_TITLE).lower()
            )
            item.setHidden(not visible)

    def clear_filter(self) -> None:
        for i in range(self.topLevelItemCount()):
            self.topLevelItem(i).setHidden(False)

    def to_list(self) -> list[dict]:
        """Serialise all items to a list of dicts."""
        result = []
        for i in range(self.topLevelItemCount()):
            it = self.topLevelItem(i)
            result.append({
                "track":    it.text(self.COL_TRACK),
                "artist":   it.text(self.COL_ARTIST),
                "album":    it.text(self.COL_ALBUM),
                "title":    it.text(self.COL_TITLE),
                "duration": it.text(self.COL_DUR),
                "path":     it.data(0, Qt.ItemDataRole.UserRole),
            })
        return result

    def from_list(self, data: list[dict], replace: bool = True) -> int:
        """
        Load tracks from a list of dicts.
        If *replace* is True the playlist is cleared first.
        Returns the count of successfully added items.
        """
        if replace:
            self.clear_all()
        count = 0
        for d in data:
            path = d.get("path", "")
            if path and os.path.exists(path):
                item = self.add_track(
                    path,
                    d.get("track",    ""),
                    d.get("artist",   "Unknown"),
                    d.get("album",    ""),
                    d.get("title",    os.path.basename(path)),
                    d.get("duration", ""),
                )
                if item is not None:
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def item_at_row(self, row: int) -> Optional[QTreeWidgetItem]:
        if 0 <= row < self.topLevelItemCount():
            return self.topLevelItem(row)
        return None

    def path_of(self, item: QTreeWidgetItem) -> str:
        return item.data(0, Qt.ItemDataRole.UserRole)
