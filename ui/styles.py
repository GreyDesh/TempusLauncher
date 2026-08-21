DARK_GLASS_QSS = """
/* === Base === */
* {
    font-family: 'Rubik', 'Manrope', 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
    color: #E6EDF3;
}

QWidget {
    background: transparent;
}

QMainWindow, QDialog {
    background: #0E1117;
}

/* === Scrollbar === */
QScrollBar:vertical {
    background: rgba(255,255,255,5);
    width: 4px;
    border-radius: 2px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(63,185,80,100);
    border-radius: 2px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    background: rgba(255,255,255,5);
    height: 4px;
    border-radius: 2px;
}
QScrollBar::handle:horizontal {
    background: rgba(63,185,80,100);
    border-radius: 2px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* === Sidebar === */
#sidebar {
    background: #0D1117;
    border-right: 1px solid rgba(255,255,255,8);
    border-top-left-radius: 14px;
    border-bottom-left-radius: 14px;
}

/* === Top bar === */
#topBar {
    background: rgba(13,17,23,220);
    border-bottom: 1px solid rgba(255,255,255,8);
}

/* === Tab buttons === */
QPushButton[class="tab"] {
    background: transparent;
    color: #7D8590;
    border: none;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
}
QPushButton[class="tab"]:hover {
    color: #E6EDF3;
    background: rgba(255,255,255,5);
    border-radius: 6px;
}
QPushButton[class="tab"][active="true"] {
    color: #3FB950;
    border-bottom: 2px solid #3FB950;
}

/* === Inputs === */
QLineEdit {
    background: rgba(255,255,255,6);
    border: 1px solid rgba(255,255,255,12);
    border-radius: 10px;
    padding: 10px 14px 10px 42px;
    color: #E6EDF3;
    font-size: 13px;
    selection-background-color: rgba(63,185,80,60);
}
QLineEdit:focus {
    border: 1px solid rgba(63,185,80,140);
    background: rgba(63,185,80,8);
}
QLineEdit::placeholder {
    color: #4A5260;
}

/* === Standard buttons === */
QPushButton {
    background: rgba(63,185,80,200);
    color: #ffffff;
    border: none;
    border-radius: 10px;
    padding: 10px 22px;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.5px;
}
QPushButton:hover {
    background: rgba(63,185,80,240);
}
QPushButton:pressed {
    background: rgba(46,160,67,230);
}
QPushButton:disabled {
    background: rgba(60,68,80,160);
    color: rgba(180,190,210,80);
}

QPushButton[class="secondary"] {
    background: rgba(255,255,255,8);
    color: #A0AAB8;
    border: 1px solid rgba(255,255,255,12);
}
QPushButton[class="secondary"]:hover {
    background: rgba(255,255,255,14);
    color: #E6EDF3;
}

QPushButton[class="danger"] {
    background: rgba(218,54,51,180);
}
QPushButton[class="danger"]:hover {
    background: rgba(218,54,51,220);
}

/* === Labels === */
QLabel[class="h1"] {
    font-size: 26px;
    font-weight: 700;
    color: #E6EDF3;
}
QLabel[class="h2"] {
    font-size: 18px;
    font-weight: 700;
    color: #E6EDF3;
}
QLabel[class="dim"] {
    color: #7D8590;
    font-size: 12px;
}
QLabel[class="accent"] {
    color: #3FB950;
    font-weight: 600;
}
QLabel[class="online"] {
    color: #3FB950;
    font-size: 11px;
}

/* === Progress bar === */
QProgressBar {
    background: rgba(255,255,255,8);
    border-radius: 3px;
    border: none;
    height: 4px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3FB950, stop:1 #00B8D9);
    border-radius: 3px;
}

/* === Slider === */
QSlider::groove:horizontal {
    background: rgba(255,255,255,10);
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #3FB950;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal {
    background: #3FB950;
    border-radius: 2px;
}

/* === Checkbox === */
QCheckBox {
    spacing: 8px;
    color: #A0AAB8;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid rgba(255,255,255,20);
    background: rgba(255,255,255,6);
}
QCheckBox::indicator:checked {
    background: #3FB950;
    border: 1px solid #3FB950;
}

/* === TextEdit (logs) === */
QTextEdit {
    background: #0D1117;
    border: 1px solid rgba(255,255,255,10);
    border-radius: 8px;
    color: #7EE787;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 11px;
    padding: 8px;
}

/* === ComboBox === */
QComboBox {
    background: rgba(255,255,255,8);
    border: 1px solid rgba(255,255,255,12);
    border-radius: 8px;
    padding: 7px 12px;
    color: #E6EDF3;
}
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background: #1B1F24;
    border: 1px solid rgba(255,255,255,12);
    selection-background-color: rgba(63,185,80,50);
    color: #E6EDF3;
    outline: none;
}

/* === Tooltip === */
QToolTip {
    background: #1B1F24;
    border: 1px solid rgba(255,255,255,15);
    color: #E6EDF3;
    padding: 5px 10px;
    border-radius: 6px;
}

/* === Dialog === */
QDialog {
    background: #0E1117;
}
"""
