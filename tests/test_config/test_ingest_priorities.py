"""Нижняя граница ``RABBITMQ_MAX_PRIORITY`` — это ``PRIO_LIVE``, литералом.

``src/config.py`` намеренно НЕ импортирует ``src.intake.queue.priorities``:
настройки импортируют все, в том числе ядро, и такой импорт протаскивал бы
контур приёма в ядро транзитивно, оставляя arch-тест зелёным при нарушенной
границе (сам запрет живёт в ``tests/test_intake/test_boundaries.py``, где
``src/config.py`` стоит в списке проверяемых файлов).

Цена развязки — литерал ``ge=5``, который может разъехаться с константой;
этот файл и есть страховка от расхождения — тот же приём, что
``tests/test_scripts/test_setup_db_authz.py`` для ``_FULL_SCOPES_SQL``.

Проверяется ровно граница, а не умолчание: ``max_priority`` ниже живого
приоритета провалил бы маршрутную проверку ``0 <= PRIO_LIVE <= max_priority``
и отдал бы 422 на КАЖДОЙ обычной заливке.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import RabbitMQSettings
from src.intake.queue.priorities import PRIO_LIVE


def test_max_priority_floor_matches_prio_live() -> None:
    # Явный аргумент конструктора старше .env, поэтому тест не зависит от
    # того, выставлен ли RABBITMQ_MAX_PRIORITY в окружении прогона.
    assert RabbitMQSettings(max_priority=PRIO_LIVE).max_priority == PRIO_LIVE
    with pytest.raises(ValidationError):
        RabbitMQSettings(max_priority=PRIO_LIVE - 1)
