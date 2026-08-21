import sys
from PyQt6.QtGui import QPixmap, QPainter, QColor, QIcon
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtSvg import QSvgRenderer
import asset_pack


def _pix(name: str) -> QPixmap:
    data = asset_pack.read(f"assets/{name}")
    if data is None:
        return QPixmap()
    px = QPixmap()
    px.loadFromData(data)
    return px


def mimi_grand() -> QPixmap:     return _pix("mimi_grand.png")
def not_role_pig() -> QPixmap:   return _pix("not_role_pig.png")
def not_discord() -> QPixmap:    return _pix("not_discord.png")
def discord_icon() -> QPixmap:   return _pix("discord_icon.png")
def telegram_icon() -> QPixmap:  return _pix("telegram_icon.png")
def launcher_logo() -> QPixmap:  return _pix("launcher_logo.png")


def assets_path(name: str) -> str | None:
    """Возвращает None — используй svg_icon() или _pix() вместо пути к файлу."""
    return None


def svg_icon(name: str, color: str = "#E6EDF3", size: int = 18) -> QIcon:
    data = asset_pack.read(f"assets/{name}")
    if data is None:
        return QIcon()
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(data))
    painter = QPainter(px)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(px.rect(), QColor(color))
    painter.end()
    return QIcon(px)
