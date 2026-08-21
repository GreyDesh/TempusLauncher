from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QRadialGradient, QFont, QPen
from PyQt6.QtWidgets import QWidget


class GlowButton(QWidget):
    """Кнопка с градиентом и анимированным glow-эффектом."""
    clicked = pyqtSignal()

    def __init__(self, text: str = "PLAY", color: str = "#3FB950", parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self._glow_alpha = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(140)

        self._anim = QPropertyAnimation(self, b"glowAlpha")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_glow_alpha(self) -> float:
        return self._glow_alpha

    def set_glow_alpha(self, v: float):
        self._glow_alpha = v
        self.update()

    glowAlpha = pyqtProperty(float, get_glow_alpha, set_glow_alpha)

    def setText(self, text: str):
        self._text = text
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 10

        # Glow ореол
        if self._glow_alpha > 0:
            glow = QRadialGradient(w / 2, h, w * 0.7)
            c = QColor(self._color)
            c.setAlpha(int(80 * self._glow_alpha))
            glow.setColorAt(0, c)
            c2 = QColor(self._color)
            c2.setAlpha(0)
            glow.setColorAt(1, c2)
            p.setBrush(glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(-20, -20, w + 40, h + 40, r + 20, r + 20)

        # Основной градиент кнопки
        grad = QLinearGradient(0, 0, 0, h)
        light = self._color.lighter(115)
        dark = self._color.darker(115)
        grad.setColorAt(0, light)
        grad.setColorAt(1, dark)
        p.setBrush(grad)

        # Бордер
        border = QColor(self._color.lighter(130))
        border.setAlpha(120)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # Highlight (верхняя полоска)
        hi = QLinearGradient(0, 0, 0, h // 2)
        hi_c = QColor(255, 255, 255, int(40 + 30 * self._glow_alpha))
        hi_c2 = QColor(255, 255, 255, 0)
        hi.setColorAt(0, hi_c)
        hi.setColorAt(1, hi_c2)
        p.setBrush(hi)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, w - 4, h // 2, r, r)

        # Текст
        font = QFont("Rubik", 13, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, self._text)

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class SplitGlowButton(QWidget):
    """Кнопка с основным действием слева и иконкой настроек справа."""
    clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    kill_requested = pyqtSignal()

    _GEAR_W = 36

    def __init__(self, text: str = "PLAY", color: str = "#3FB950", parent=None):
        super().__init__(parent)
        self._text = text
        self._display_text = text   # текст который реально рисуется (может меняться при hover)
        self._color = QColor(color)
        self._glow_alpha = 0.0
        self._hover_gear = False
        self._hover_main = False    # наведение на основную часть
        self._pressed = False       # основная часть зажата (тактильный отклик)
        self._running = False       # режим "игра запущена"
        self._icon_px = None
        self._icon_svg = "play.svg"
        try:
            from ui.assets import svg_icon as _svg
            self._icon_px = _svg("play.svg", "#ffffff", 16).pixmap(16, 16)
        except Exception:
            pass
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(140 + self._GEAR_W)
        self.setMouseTracking(True)

        self._anim = QPropertyAnimation(self, b"glowAlpha")
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def get_glow_alpha(self) -> float:
        return self._glow_alpha

    def set_glow_alpha(self, v: float):
        self._glow_alpha = v
        self.update()

    glowAlpha = pyqtProperty(float, get_glow_alpha, set_glow_alpha)

    def setText(self, text: str):
        self._text = text
        self._display_text = text
        self._pressed = False
        self.update()

    def set_icon_svg(self, svg_name: str):
        try:
            from ui.assets import svg_icon as _svg
            self._icon_px = _svg(svg_name, "#ffffff", 16).pixmap(16, 16)
        except Exception:
            self._icon_px = None
        self.update()

    def set_running(self, running: bool):
        """Переключает кнопку в режим 'игра запущена'."""
        self._running = running
        self._display_text = self._text
        self._pressed = False
        self.update()

    def _gear_rect(self):
        from PyQt6.QtCore import QRect
        return QRect(self.width() - self._GEAR_W, 0, self._GEAR_W, self.height())

    def _main_rect(self):
        from PyQt6.QtCore import QRect
        return QRect(0, 0, self.width() - self._GEAR_W, self.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 10
        gw = self._GEAR_W
        main_w = w - gw

        # Glow
        if self._glow_alpha > 0:
            from PyQt6.QtGui import QRadialGradient
            glow = QRadialGradient(main_w / 2, h, main_w * 0.7)
            c = QColor(self._color); c.setAlpha(int(80 * self._glow_alpha))
            glow.setColorAt(0, c)
            c2 = QColor(self._color); c2.setAlpha(0)
            glow.setColorAt(1, c2)
            p.setBrush(glow); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(-20, -20, main_w + 40, h + 40, r + 20, r + 20)

        # Основная часть (левая)
        from PyQt6.QtGui import QLinearGradient
        grad = QLinearGradient(0, 0, 0, h)
        if self._pressed:
            grad.setColorAt(0, self._color.darker(130))
            grad.setColorAt(1, self._color.darker(150))
        else:
            grad.setColorAt(0, self._color.lighter(115))
            grad.setColorAt(1, self._color.darker(115))
        p.setBrush(grad)
        border = QColor(self._color.lighter(130)); border.setAlpha(120)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, r, r)

        # Перекрасить правую часть поверх (gear zone)
        gear_bg = QColor(0, 0, 0, 50 if self._hover_gear else 30)
        p.setBrush(gear_bg); p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(main_w, 1, gw - 1, h - 2)
        # Скруглить правые углы отдельно
        p.drawRoundedRect(main_w, 1, gw - 1, h - 2, r, r)

        # Разделитель
        div_color = QColor(self._color.lighter(130)); div_color.setAlpha(80)
        p.setPen(QPen(div_color, 1))
        p.drawLine(main_w, 6, main_w, h - 6)

        # Highlight верхняя полоска (при нажатии убираем — эффект "вдавлено")
        if not self._pressed:
            hi = QLinearGradient(0, 0, 0, h // 2)
            hi.setColorAt(0, QColor(255, 255, 255, int(40 + 30 * self._glow_alpha)))
            hi.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(hi); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(2, 2, w - 4, h // 2, r, r)

        # Текст + иконка основной части (при нажатии сдвигаем на 1px вниз)
        dy = 1 if self._pressed else 0
        p.setFont(QFont("Rubik", 13, QFont.Weight.Bold))
        p.setPen(QColor(255, 255, 255, 230))
        if self._icon_px and not self._icon_px.isNull():
            fm = p.fontMetrics()
            txt_w = fm.horizontalAdvance(self._display_text)
            icon_w = 16
            gap = 6
            total = icon_w + gap + txt_w
            x0 = (main_w - total) // 2
            p.drawPixmap(x0, (h - 16) // 2 + dy, self._icon_px)
            p.drawText(x0 + icon_w + gap, dy, txt_w + 4, h, Qt.AlignmentFlag.AlignVCenter, self._display_text)
        else:
            p.drawText(0, dy, main_w, h, Qt.AlignmentFlag.AlignCenter, self._display_text)

        # Иконка настроек (SVG)
        try:
            from ui.assets import svg_icon as _svg
            alpha = 200 if self._hover_gear else 160
            color_hex = f"rgba(255,255,255,{alpha})"
            ico_px = _svg("settings.svg", "#ffffff", 16).pixmap(16, 16)
            ico_px.setAlphaChannel(ico_px.scaled(16, 16))
            p.setOpacity(alpha / 255)
            p.drawPixmap(main_w + (gw - 16) // 2, (h - 16) // 2, ico_px)
            p.setOpacity(1.0)
        except Exception:
            p.setFont(QFont("Segoe UI", 13))
            p.setPen(QColor(255, 255, 255, 200 if self._hover_gear else 160))
            p.drawText(main_w, 0, gw, h, Qt.AlignmentFlag.AlignCenter, "⚙")

    def mouseMoveEvent(self, event):
        in_gear = event.position().x() >= self.width() - self._GEAR_W
        in_main = not in_gear
        self._hover_gear = in_gear
        if self._running:
            if in_main and not self._hover_main:
                self._hover_main = True
                self._display_text = "  Закрыть"
                self._color = QColor("#ff5c5c")
                self.set_icon_svg("cross.svg")
                self.update()
            elif not in_main and self._hover_main:
                self._hover_main = False
                self._display_text = self._text
                self._color = QColor("#6E40C9")
                self.set_icon_svg("play.svg")
                self.update()
        else:
            self.update()

    def enterEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, event):
        self._hover_gear = False
        self._hover_main = False
        if self._running:
            self._display_text = self._text
            self._color = QColor("#6E40C9")
            self.set_icon_svg("play.svg")
        self._anim.stop()
        self._anim.setStartValue(self._glow_alpha)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() >= self.width() - self._GEAR_W:
                self.settings_clicked.emit()
            elif self._running:
                self.kill_requested.emit()
            else:
                # Тактильный отклик: сразу рисуем "продавленное" состояние ДО обработчика
                # clicked (он может блокировать UI-поток на рефреш токена).
                self._pressed = True
                self.repaint()
                self.clicked.emit()

    def mouseReleaseEvent(self, event):
        if self._pressed:
            self._pressed = False
            self.update()


class SecondaryButton(QWidget):
    """Вторичная кнопка — прозрачная с рамкой."""
    clicked = pyqtSignal()

    def __init__(self, text: str = "", icon: str = "", parent=None):
        super().__init__(parent)
        self._text = text
        self._icon = icon
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(38)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        bg = QColor(255, 255, 255, 18 if self._hover else 8)
        border = QColor(255, 255, 255, 35 if self._hover else 18)
        p.setBrush(bg)
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(1, 1, w - 2, h - 2, 10, 10)

        font = QFont("Rubik", 12)
        p.setFont(font)
        p.setPen(QColor(180, 190, 210))
        label = f"{self._icon}  {self._text}" if self._icon and self._text else self._icon or self._text
        p.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, label)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
