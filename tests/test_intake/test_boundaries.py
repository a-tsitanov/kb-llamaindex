"""Граница контуров приёма и ядра — исполняемый arch-тест, а не договорённость.

Образец — ``tests/test_no_neo4j.py``, но разбор идёт по AST, а не регуляркой:
ленивые импорты внутри функций здесь обычное дело (``src/mcp/tools_server.py``,
``src/workflow/_search_deps.py``), и построчный поиск их либо потеряет, либо
поймает упоминание в комментарии.

Четыре решения, зафиксированные здесь намеренно:

(а) **Почему исключений два, а не одно, как в §3.2.** Вердикт классификатора
    исполняет воркер: ``classify_document`` держит LLM-гейт вне HTTP-запроса
    (I6), а ``mark_skipped`` записывает результат этого же гейта.  Обе
    активности — воркер-сторона приёма, поэтому исключение одно по смыслу и
    два по файлам: ``classify_document.py`` и ``mark_skipped.py``, каждая
    активность в своём модуле.  Список именно файловый, а не «по
    активностям»: ``test_allowlist_entries_exist`` обязан падать на
    несуществующем пути, иначе забытое исключение тихо расширит правило.

(б) **Почему src/storage в правилах не фигурирует.** ``src/storage`` — общая
    инфраструктура НИЖЕ обоих контуров, а не ядро: сам приём импортирует
    ``src.storage.pg_scope``, а ``src/storage/chunk_repository.py`` строит
    ``IntakeRepository`` умолчанием.  §3.2 перечисляет ядром ``src/graph``,
    ``src/retrieval`` и ``src/workflow``, и расширять этот список на storage
    значило бы запретить легальное направление.

(в) **Почему в правиле 1 есть src/config.py.** Префиксы ядра — про
    раскладку, но ``src/config.py`` импортируют ВСЕ, ядро в том числе, и
    импорт приёма в настройках протаскивал бы приём в ядро транзитивно: до
    этой правки ``import src.retrieval.vector_index`` поднимал
    ``src.intake.queue.priorities`` через ``src/config.py``, а правило 1
    оставалось зелёным, потому что сам файл под префиксы не попадает.
    Общий транзитивный запрет здесь не годится: ``src/storage`` ниже обоих
    контуров и импортирует приём законно (пункт «б»), так что правило
    перечисляет файлы, а не считает замыкание.

(г) **Почему правило 3 нужно рядом с рантайм-проверкой.** Транзитивный путь
    ``src/workflow`` → ``src/storage/chunk_repository`` → ``src/intake``
    допустим (см. «б»), а прямая инжекция ядрового ``AsyncPostgres`` в
    конструктор чужого контура — нет: у него больше нет ни ``get``, ни
    ``list_id_path``, поэтому возврат ``pg=`` в любую из двух точек сборки
    (``src/mcp/tools_server.py``, ``src/workflow/_search_deps.py``) всплыл бы
    только AttributeError'ом на живом стенде.  Рантайм-проверка
    ``tests/test_storage/test_chunk_repository.py::test_default_pg_is_intake_repository``
    утверждает САМО умолчание, но на своём объекте, а не в тех двух вызовах;
    форму вызова там сторожит правило 3 по AST.  Защиты дополняют друг друга,
    поэтому здесь обе.

Правила ниже — про раскладку контуров, поэтому смотрят только ``src/``.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

# Контуры: ядро (слева) не знает о приёме (справа).
_CORE_PREFIXES = ("src/graph/", "src/retrieval/", "src/workflow/")
# Файлы ВНЕ префиксов ядра, на которые правило 1 распространяется всё равно:
# их импортирует ядро, поэтому импорт приёма здесь — тот же импорт приёма в
# ядре, только транзитивный. См. пункт (в) докстринга.
_CORE_SHARED_FILES = ("src/config.py",)
_INTAKE_PREFIX = "src/intake/"

# Воркер-сторона приёма — единственное объявленное исключение из правила 1,
# см. пункт (а) докстринга.
_INTAKE_WORKER_ADAPTERS = {
    "src/workflow/activities/classify_document.py",
    "src/workflow/activities/mark_skipped.py",
}


# ── разбор AST ───────────────────────────────────────────────────────


def _py_files(*roots: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for root in roots for p in root.rglob("*.py") if p.is_file())


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _parse(path: pathlib.Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST, *, pkg: tuple[str, ...] = ()) -> list[tuple[int, str]]:
    """Все импортируемые модули как (строка, точечное имя), включая ленивые.

    Для ``from X import Y`` возвращается и сам ``X``, и ``X.Y``: иначе
    ``from src import intake`` проскочит мимо правила.  Относительные импорты
    (в src их сегодня нет) разворачиваются в абсолютные по пакету файла,
    чтобы обход не зависел от стиля записи.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = ".".join(pkg[: len(pkg) - (node.level - 1)])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            if not module:
                continue
            found.append((node.lineno, module))
            found += [(node.lineno, f"{module}.{alias.name}") for alias in node.names]
    return found


def _is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _module_imports(path: pathlib.Path, package: str) -> list[str]:
    """Нарушения правил 1-2 для одного файла: «файл:строка → модуль».

    Один оператор импорта — одна строка отчёта: ``from X import Y`` даёт в
    ``_imports`` обе формы, и без схлопывания по строке отчёт двоился бы.
    """
    pkg = path.relative_to(ROOT).parent.parts
    by_line: dict[int, str] = {}
    for lineno, module in _imports(_parse(path), pkg=pkg):
        if not _is_under(module, package):
            continue
        shortest = by_line.get(lineno)
        if shortest is None or len(module) < len(shortest):
            by_line[lineno] = module
    return [f"{_rel(path)}:{lineno} → {module}" for lineno, module in sorted(by_line.items())]


def _call_name(func: ast.expr) -> str:
    """Имя вызываемого: ``X(...)`` → ``X``, ``mod.X(...)`` → ``X``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _pg_injections(tree: ast.AST, label: str) -> list[str]:
    """Нарушения правила 3 в одном разобранном модуле: «файл:строка → вызов».

    Ищется ровно запрещённая форма — ``pg=`` со значением-вызовом
    ``AsyncPostgres(...)`` в конструкторе ``ChunkRepository``.  Локальные
    псевдонимы класса намеренно не отслеживаются: цель — поймать возврат
    убранной инжекции, а не любую её обфускацию.
    """
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "ChunkRepository":
            continue
        out += [
            f"{label}:{node.lineno} → ChunkRepository(pg=AsyncPostgres(...))"
            for kw in node.keywords
            if kw.arg == "pg"
            and isinstance(kw.value, ast.Call)
            and _call_name(kw.value.func) == "AsyncPostgres"
        ]
    return out


# ── правила ──────────────────────────────────────────────────────────


def test_core_does_not_import_intake():
    """ПРАВИЛО 1: ядро не знает о приёме, кроме воркер-адаптеров."""
    violations: list[str] = []
    for path in _py_files(SRC):
        rel = _rel(path)
        checked = rel.startswith(_CORE_PREFIXES) or rel in _CORE_SHARED_FILES
        if not checked or rel in _INTAKE_WORKER_ADAPTERS:
            continue
        violations += _module_imports(path, "src.intake")
    assert not violations, "ядро импортирует приём:\n" + "\n".join(violations)


def test_intake_does_not_import_graph():
    """ПРАВИЛО 2: приём не знает о графовом контуре."""
    violations: list[str] = []
    for path in _py_files(SRC):
        if _rel(path).startswith(_INTAKE_PREFIX):
            violations += _module_imports(path, "src.graph")
    assert not violations, "приём импортирует граф:\n" + "\n".join(violations)


def test_core_does_not_inject_async_postgres():
    """ПРАВИЛО 3: ядровой ``AsyncPostgres`` не инжектируется в ChunkRepository."""
    violations: list[str] = []
    for path in _py_files(SRC):
        violations += _pg_injections(_parse(path), _rel(path))
    assert not violations, (
        "инжекция AsyncPostgres в ChunkRepository (умолчание — IntakeRepository):\n"
        + "\n".join(violations)
    )


# ── гарды самого теста ───────────────────────────────────────────────


def test_allowlist_entries_exist():
    """Устаревшее исключение тихо расширяет правило 1 — ловим это сразу."""
    for rel in sorted(_INTAKE_WORKER_ADAPTERS):
        path = ROOT / rel
        assert path.is_file(), f"{rel}: исключение указывает на несуществующий файл"
        assert _module_imports(path, "src.intake"), (
            f"{rel}: файл больше не импортирует src.intake — исключение пора убрать"
        )


def test_core_shared_files_exist():
    """Переименованный файл тихо вывел бы себя из-под правила 1."""
    for rel in _CORE_SHARED_FILES:
        assert (ROOT / rel).is_file(), f"{rel}: файл проверяемого набора пропал"


def test_allowlist_is_minimal():
    """Воркер-адаптеру положены классификатор и репозиторий приёма, но не его маршруты."""
    for rel in sorted(_INTAKE_WORKER_ADAPTERS):
        assert _module_imports(ROOT / rel, "src.intake.api") == []


def test_rule3_catches_synthetic_violation():
    """Опечатка в обходе AST сделала бы правило 3 вечнозелёным."""
    bad = "ChunkRepository(graph=g, pg=AsyncPostgres(graph=g))"
    assert _pg_injections(ast.parse(bad), "<образец>")
    # Текущая форма обоих вызовов — без ``pg=``; она обязана оставаться чистой.
    assert _pg_injections(ast.parse("ChunkRepository(graph=g)"), "<образец>") == []
