"""Граница контура наблюдения — исполняемый arch-тест.

Разбор AST и хелперы переиспользуются из arch-теста приёма
(``tests/test_intake/test_boundaries.py``): правила разные, механика
одна, и второй её экземпляр разъехался бы с первым при следующей правке
(так же, как ``tests/test_retrieval`` берёт фейки из ``tests/test_graph``).

Правила здесь ДВА, и каждое исключение названо файлом, а не описано
словами: список проверяется на существование путей, иначе забытое
исключение тихо расширило бы правило.

Почему у правила 4 три исключения, а не ноль. Наблюдение питается
графом, и три направления связи реальны:

* ``src/workflow/worker.py`` — корень сборки: он регистрирует В Temporal
  всё, что есть в проекте, включая активности наблюдения. Запретить ему
  знать о наблюдении значит запретить наблюдению исполняться;
* ``src/workflow/activities/build_property_graph.py`` — запись журналов
  на ингесте: журнал наполняет ядро, в момент, когда оно создало узлы и
  связи. Это тот же тип исключения, что воркерные адаптеры приёма;
* ``src/graph/entity_resolution.py`` — слияние сущностей переписывает
  vid в журналах: без этого подписка на слитую сущность перестала бы
  получать события, а подписчик об этом бы не узнал. Инверсия (чтобы
  наблюдение подписывалось на слияния) потребовала бы собственной шины
  событий внутри графа — отдельная задача, не эта.

Чего в правилах НЕТ: ``src/api`` и ``src/mcp`` — это точки входа, они по
определению знают про все контуры (там же живут швы авторизации).
"""

from __future__ import annotations

import pathlib

from tests.test_intake.test_boundaries import (
    ROOT,
    SRC,
    _module_imports,
    _py_files,
    _rel,
)

_CORE_PREFIXES = ("src/graph/", "src/retrieval/", "src/workflow/")
_WATCH_PREFIX = "src/watch/"

# Объявленные направления связи ядро → наблюдение (см. докстринг).
_WATCH_ADAPTERS = {
    "src/workflow/worker.py",
    "src/workflow/activities/build_property_graph.py",
    "src/graph/entity_resolution.py",
}

# Единственное, что наблюдение знает о приёме: провенанс документа
# (источник, вердикт приёма, владелец тела).  SQL по ``documents``
# остаётся в приёме — отсюда метод, а не собственный запрос.
_INTAKE_READ_ALLOWED = "src.intake.repository"


def test_core_does_not_import_watch() -> None:
    """ПРАВИЛО 4: ядро не знает о наблюдении, кроме трёх адаптеров."""
    violations: list[str] = []
    for path in _py_files(SRC):
        rel = _rel(path)
        if not rel.startswith(_CORE_PREFIXES) or rel in _WATCH_ADAPTERS:
            continue
        violations += _module_imports(path, "src.watch")
    assert not violations, "ядро импортирует наблюдение:\n" + "\n".join(violations)


def test_watch_reads_intake_only_through_the_repository() -> None:
    """ПРАВИЛО 5: наблюдение не лезет в приём мимо реестра.

    Маршруты, очередь и классификатор приёма наблюдению не нужны вовсе;
    нужен один вопрос — «что это за документ», — и его задают реестру.
    """
    violations: list[str] = []
    for path in _py_files(SRC):
        if not _rel(path).startswith(_WATCH_PREFIX):
            continue
        violations += [
            entry
            for entry in _module_imports(path, "src.intake")
            if not entry.split(" → ")[1].startswith(_INTAKE_READ_ALLOWED)
        ]
    assert not violations, (
        "наблюдение импортирует приём мимо реестра:\n" + "\n".join(violations)
    )


def test_adapter_allowlist_entries_exist() -> None:
    """Исключение на несуществующий путь — тихо расширенное правило."""
    missing = [rel for rel in sorted(_WATCH_ADAPTERS) if not (ROOT / rel).is_file()]
    assert not missing, f"адаптеры из списка исключений не существуют: {missing}"


def test_the_watch_package_is_where_the_rules_look() -> None:
    """Страховка от переименования пакета: правила смотрят по префиксу, и
    переезд каталога оставил бы их зелёными ни на чём."""
    assert (pathlib.Path(ROOT) / _WATCH_PREFIX).is_dir()
    assert any(_rel(p).startswith(_WATCH_PREFIX) for p in _py_files(SRC))
