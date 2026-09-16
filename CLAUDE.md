# CLAUDE.md

Платформенные примитивы для VK Mini Apps на Yandex Cloud Functions + YDB.

## Команды

```bash
uv sync              # установить окружение
uv run pytest        # тесты
uv run ruff check .  # линт
```

## Структура

Src-layout: код — в `src/vkyc/`. Корневой `__init__.py` пустой, без реэкспорта — импортировать нужно конкретный подпакет (`from vkyc.auth import ...`), а не пакет целиком. `extras` в `pyproject.toml` появятся позже, когда в пакете возникнут подпакеты с тяжёлыми сторонними зависимостями, нужными не всем потребителям.
