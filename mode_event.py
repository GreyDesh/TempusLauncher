# Утилита для отображения событий режима (закрытие/открытие/ивент).
from datetime import datetime, timezone


_LABELS = {
    "closing": "Закрытие",
    "opening": "Открытие",
    "event":   "Ивент",
}


def get_event_parts(mode: dict) -> tuple[str, str]:
    """Возвращает (label, value) для StatBlock, например ('Открытие', 'через 3 дня').
    Оба пустые если события нет или оно неактивно."""
    ev = mode.get("event")
    if not ev or not ev.get("active", False):
        return "", ""
    kind = ev.get("type", "event")
    date_str = ev.get("date", "")
    if not date_str:
        return "", ""
    try:
        dt = datetime.fromisoformat(date_str)
        # Наивную дату трактуем как ЛОКАЛЬНОЕ время (админ вводит своё время),
        # дату с указанным поясом — как есть. Сравниваем с локальным «сейчас».
        # OLD
        if dt.tzinfo is None:
            dt = dt.astimezone()
        now = datetime.now().astimezone()
        secs = (dt - now).total_seconds()
        label = _LABELS.get(kind, "Событие")

        if secs <= 0:
            value = "Сейчас"
        else:
            days = int(secs // 86400)
            if days >= 1:
                # 1 день; 2-4 дня; 5+ дней (по последней цифре, с учётом 11-14) (как в steam)
                d10, d100 = days % 10, days % 100
                if d10 == 1 and d100 != 11:
                    value = f"{days} день"
                elif 2 <= d10 <= 4 and not (12 <= d100 <= 14):
                    value = f"{days} дня"
                else:
                    value = f"{days} дней"
            else:
                hours = int(secs // 3600)
                if hours >= 1:
                    value = f"{hours} ч"
                else:
                    mins = int(secs // 60)
                    value = f"{mins} мин" if mins >= 1 else "Скоро"
        return label, value
    except Exception:
        return "", ""


def get_event_text(mode: dict) -> str:
    """Одна строка для карточек/сайдбара."""
    label, value = get_event_parts(mode)
    if not label:
        return ""
    return f"{label}: {value}"
