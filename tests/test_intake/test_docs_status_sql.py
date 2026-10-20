"""Операторский SQL в документации не читает статус из ``documents``.

Запись расщеплена (S8): приём пишет ``documents``, обработка —
``doc_processing``, а в ``documents.status`` у принятого документа навсегда
остаётся 'pending' (I8).  Любая команда вида «SELECT status … FROM documents»
после этого не падает и не ругается — она молча врёт, и именно в этом виде
прожила ревью: грепы по именам классов и методов (`status_counts_by`,
`insert_pending`) такие места найти не могут, потому что ни класса, ни метода
в них не названо.

Правило: SQL по ``documents``, который называет ``status`` или ``error``,
обязан джойнить ``doc_processing`` — иначе он показывает дорасщеплённое
значение.  Канон выражения — ``IntakeRepository.EFFECTIVE_STATUS``; в
документации лучше ссылаться на готовые поверхности
(``python -m scripts.check_ingestion``, ``GET /api/v1/stats/messages``), чем
копировать выражение четвёртый раз.

Разбор строчный, и это осознанно: проверяются операторские однострочники в
markdown — таблицы «частых операций» и runbook'и.  Многострочный SQL в коде
(``scripts/check_ingestion.py``, ``deploy/offline/loadtest/monitor.sh``) берёт
выражение из репозитория приёма и сторожится обычным ревью.

``docs/superpowers/`` исключён: спеки и планы — замороженные записи решений,
и SQL в них цитируется таким, каким он был на момент решения.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Где ищем: операторская документация и файлы выката.
_SCAN_DIRS = ("docs", "deploy")
_SKIP_DIRS = ("docs/superpowers/",)

# «SELECT … FROM documents» в одной строке, с group by в том же виде.
_FROM_DOCUMENTS = re.compile(r"\bfrom\s+documents\b", re.IGNORECASE)
_NAMES_PROCESSING = re.compile(r"\bdoc_processing\b", re.IGNORECASE)
_NAMES_STATUS = re.compile(r"\b(status|error)\b", re.IGNORECASE)


def _md_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in _SCAN_DIRS:
        for path in (ROOT / d).rglob("*.md"):
            rel = path.relative_to(ROOT).as_posix()
            if not rel.startswith(_SKIP_DIRS):
                out.append(path)
    return sorted(out)


def test_docs_do_not_read_status_from_documents_alone() -> None:
    violations: list[str] = []
    for path in _md_files():
        rel = path.relative_to(ROOT).as_posix()
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            if not _FROM_DOCUMENTS.search(line):
                continue
            # Строка, которая только НАЗЫВАЕТ расщепление («в documents.status
            # никто не пишет»), под правило не попадает: её SQL-часть должна
            # содержать и status/error, и отсутствие join'а.
            if not _NAMES_STATUS.search(line):
                continue
            if _NAMES_PROCESSING.search(line):
                continue
            violations.append(f"{rel}:{lineno}: {line.strip()}")
    assert not violations, (
        "SQL по documents со статусом без join'а doc_processing "
        "(покажет дорасщеплённое значение):\n" + "\n".join(violations)
    )


def test_guard_catches_a_stale_snippet() -> None:
    """Опечатка в регулярках сделала бы правило вечнозелёным."""
    stale = "select status,count(*) from documents group by 1"
    assert _FROM_DOCUMENTS.search(stale) and _NAMES_STATUS.search(stale)
    assert not _NAMES_PROCESSING.search(stale)
    # А правильная форма — с join'ом — проходит.
    fixed = (
        "select coalesce(p.status, d.status), count(*) from documents d "
        "left join doc_processing p on p.doc_id = d.id group by 1"
    )
    assert _NAMES_PROCESSING.search(fixed)


def test_scanner_sees_the_operator_docs() -> None:
    """Сломанный обход путей оставил бы правило без файлов."""
    scanned = {p.relative_to(ROOT).as_posix() for p in _md_files()}
    assert "docs/DEPLOYMENT.md" in scanned
    assert "deploy/offline/DEPLOYMENT.md" in scanned
    assert not any(p.startswith("docs/superpowers/") for p in scanned)
