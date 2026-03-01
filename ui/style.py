"""
ui/style.py
Generates the application QSS stylesheet from config values.
"""

from config.settings import derive_color


def build_stylesheet(config: dict) -> str:
    cp  = config["primary_color"]
    ca  = config["accent_color"]
    cf  = config["background_color"]
    cs  = config["selection_color"]
    cp2 = derive_color(cf, 20)
    cp3 = derive_color(cf, 35)
    ff  = config.get("font_family", "Cantarell")
    ft  = config.get("font_size",   13)

    return f"""
        QMainWindow, QWidget {{
            background-color: {cf};
            color: #e0e0f0;
            font-family: '{ff}';
            font-size: {ft}px;
        }}
        #leftPanel {{
            background-color: {cf};
            border-right: 1px solid {cp3};
        }}
        #rightPanel {{ background-color: {cf}; }}
        #sectionLabel {{
            background-color: {cp3};
            color: {ca};
            font-size: 12px;
            font-weight: bold;
            padding: 6px 0;
            letter-spacing: 1px;
        }}
        QTreeView, QTreeWidget {{
            background-color: {cf};
            color: #c8d0e0;
            border: none;
            outline: none;
        }}
        QTreeView::item:hover, QTreeWidget::item:hover {{
            background-color: {cp3};
        }}
        QTreeView::item:selected, QTreeWidget::item:selected {{
            background-color: {cs};
            color: white;
        }}
        QTreeWidget::item {{
            padding: 6px 12px;
            border-bottom: 1px solid {cp2};
        }}
        QHeaderView::section {{
            background-color: #22223b;
            color: {ca};
            padding: 4px;
            border: none;
        }}
        QHeaderView::section:hover {{ background-color: {cp3}; }}
        #controlBar {{
            background-color: {cp3};
            border-top: 2px solid {cp};
        }}
        #trackLabel {{
            color: {ca};
            font-size: 13px;
            font-weight: bold;
        }}
        #controlButton {{
            background-color: {cf};
            color: #e0e0f0;
            border: 1px solid {cp3};
            border-radius: 6px;
            font-size: 14px;
        }}
        #controlButton:hover {{
            background-color: {cp};
            border-color: {cp};
            color: white;
        }}
        #controlButton:pressed {{ background-color: {cs}; }}
        #controlButton:checked {{
            background-color: {cp};
            color: white;
            border-color: {cp};
        }}
        #progressBar, #volumeSlider {{ height: 6px; }}
        #timeLabel {{
            color: {ca};
            font-size: 12px;
            font-family: monospace;
        }}
        QSlider::groove:horizontal {{
            background: {cp2};
            height: 8px;
            border-radius: 4px;
        }}
        QSlider::sub-page:horizontal {{
            background: {cp};
            border-radius: 4px;
        }}
        QSlider::handle:horizontal {{
            background: white;
            width: 18px;
            height: 18px;
            margin: -5px 0;
            border-radius: 9px;
        }}
        QScrollBar:vertical {{
            background: {cp2};
            width: 8px;
        }}
        QScrollBar::handle:vertical {{
            background: {cp3};
            border-radius: 4px;
        }}
        QStatusBar {{
            background-color: {cp3};
            color: #8899aa;
            font-size: 11px;
        }}
        #albumArt {{
            background-color: {cp3};
            border-radius: 6px;
            color: {ca};
            font-size: 32px;
        }}
        #vizTabs::pane {{ border: none; }}
        QTabBar::tab {{
            background: {cp2};
            color: #8899aa;
            padding: 4px 16px;
            border: none;
        }}
        QTabBar::tab:selected {{
            background: {cp3};
            color: {ca};
            border-bottom: 2px solid {cp};
        }}
    """
