"""Живая документация не ссылается на модули приёма, которых больше нет.

Расщепление контуров переехало маршрутами (`src/api/routes/ingest.py` →
`src/intake/api/ingest.py`, то же для `documents.py`), и пять указателей в
живых документах остались на удалённые пути: читатель runbook'а шёл искать
снапшот моделей по пути, которого нет. Тест ловит именно такой разъезд —
дешевле, чем сверять список файлов шага руками.

Два решения по объёму, принятые намеренно:

(а) **Префиксы — только `src/intake/` и `src/api/routes/`.** Это радиус
    расщепления: оба направления перехода проверяются, а чужие области не
    затаскиваются. Общая проверка «любой указатель `src/**.py` существует»
    падала бы на трёх указателях ВНЕ контура, стоявших тут до правки
    (`docs/mcp/kb-tools-contract.md`, `docs/presentation/*`,
    `docs/runbook/mcp.md`) — их починка к расщеплению не относится.

(б) **`docs/superpowers/` исключён.** Планы и спеки — записи о состоянии на
    момент решения, и переписывать в них пути значило бы править историю;
    так же их трактует сам план (§«исторические записи»).
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"

_LIVE_SUFFIXES = {".md", ".d2"}
_HISTORICAL_DIR = "superpowers"
# Путь в бэктиках, в прозе или в комментарии .d2 — все три формы одинаковы.
_POINTER = re.compile(r"src/(?:intake|api/routes)/[\w/.\-]+\.py")


def _live_docs() -> list[pathlib.Path]:
    return sorted(
        p
        for p in DOCS.rglob("*")
        if p.is_file() and p.suffix in _LIVE_SUFFIXES and _HISTORICAL_DIR not in p.parts
    )


def test_live_docs_point_at_contour_modules_that_exist() -> None:
    stale: dict[str, list[str]] = {}
    for doc in _live_docs():
        missing = sorted(
            {
                m.group(0)
                for m in _POINTER.finditer(doc.read_text(encoding="utf-8"))
                if not (ROOT / m.group(0)).exists()
            }
        )
        if missing:
            stale[str(doc.relative_to(ROOT))] = missing
    assert stale == {}, f"указатели на несуществующие модули приёма: {stale}"


def test_the_scan_sees_the_documents_it_is_supposed_to() -> None:
    """Гард самого теста: пустой обход был бы зелёным на любом разъезде."""
    docs = _live_docs()
    assert len(docs) > 20
    names = {str(p.relative_to(ROOT)) for p in docs}
    assert "docs/runbook/analytics.md" in names
    assert "docs/diagrams/ingest_flow.d2" in names
    assert not any(n.startswith("docs/superpowers/") for n in names)
