from datetime import UTC, datetime

from src.lens.model import Op
from src.lens.router import Command, Search, is_stop, route
from src.lens.state import fold


def st(*objs, hidden=(), views=()):
    ops, seq = [], 0

    def add(kind, payload, iid="i1"):
        nonlocal seq
        seq += 1
        ops.append(Op(workspace_id="w", seq=seq, kind=kind, payload=payload, input_id=iid,
                      created_at=datetime.now(UTC)))

    add("add_objects", {"objects": [{"key": k, "type": "person", "label": lbl}
                                    for k, lbl in objs]})
    for v in views:
        add("add_view", {"view": v})
    if hidden:
        add("hide", {"keys": list(hidden)}, "i2")
    return fold(ops)


S = st(("kb:1", "Си Цзиньпин"), ("kb:2", "Си Юань"), ("kb:3", "Путин В."))


def test_plain_query_is_search():
    assert route("встречи Путина в Китае", [], S) == Search("встречи Путина в Китае")


def test_undo_last_input():
    r = route("отмени", [], S)
    assert r.ops == [("undo", {"input_id": "i1"})]
    assert route("отмени", [], fold([])).reply == "Нечего отменять."


def test_hide_by_mention_and_unique_label():
    assert route("скрой", ["kb:3"], S).ops == [("hide", {"keys": ["kb:3"]})]
    assert route("скрой путин", [], S).ops == [("hide", {"keys": ["kb:3"]})]
    assert route("убери Си Цзиньпин", [], S).ops == [("hide", {"keys": ["kb:1"]})]


def test_hide_ambiguous_replies_with_candidates():
    r = route("скрой Си", [], S)
    assert isinstance(r, Command) and r.ops == []
    assert "Си Цзиньпин" in r.reply and "Си Юань" in r.reply and "@" in r.reply


def test_hide_not_found():
    r = route("скрой Байден", [], S)
    assert r.ops == [] and "Байден" in r.reply


def test_show_hidden_else_search():
    h = st(("kb:1", "Си Цзиньпин"), hidden=["kb:1"])
    assert route("покажи Си", [], h).ops == [("show", {"keys": ["kb:1"]})]
    assert route("покажи встречи в Пекине", [], h) == Search("покажи встречи в Пекине")


def test_merge_needs_two_mentions():
    assert route("да, это одно", ["kb:1", "fofa:x"], S).ops == [
        ("merge", {"keep": "kb:1", "drop": "fofa:x"})]
    assert route("объедини", ["kb:1"], S).ops == []


def test_table_from_aggregate_mention_and_modes():
    agg = {"kind": "aggregate", "key": "agg:c1:h", "label": "ip · 30", "item_type": "ip",
           "count": 30, "rows_ref": {"call_id": "c1", "path": "$.hosts[*]"},
           "columns": [{"name": "id", "path": "$.ip"}]}
    s = st(("kb:1", "X"), views=[agg])
    (kind, payload), = route("таблицей", ["agg:c1:h"], s).ops
    assert kind == "add_view"
    assert payload["view"]["kind"] == "table"
    assert payload["view"]["key"] == "table:agg:c1:h"
    assert payload["view"]["rows_ref"] == {"call_id": "c1", "path": "$.hosts[*]"}
    assert route("покажи таблицей", [], s).ops == [("set_mode", {"mode": "table"})]
    assert route("полем", [], s).ops == [("set_mode", {"mode": "canvas"})]
    assert route("IP Росатома таблицей", [], s) == Search("IP Росатома таблицей")


AGG = {"kind": "aggregate", "key": "agg:c1:h", "label": "ip · 30", "item_type": "ip",
       "count": 30, "rows_ref": {"call_id": "c1", "path": "$.hosts[*]"},
       "columns": [{"name": "id", "path": "$.ip"}]}


def test_command_words_inside_a_query_are_searches():
    s = st(("kb:1", "X"))
    assert route("отмена санкций против России", [], s) == Search(
        "отмена санкций против России")
    assert route("объедини усилия ЕС и США", [], s) == Search("объедини усилия ЕС и США")
    assert route("отмени!", [], s).ops == [("undo", {"input_id": "i1"})]


def test_word_match_not_substring():
    s = st(("kb:1", "Си Цзиньпин"), ("kb:2", "Россия"))
    assert route("скрой Си", [], s).ops == [("hide", {"keys": ["kb:1"]})]


def test_declension_matches_by_stem():
    assert route("скрой Путина", [], st(("kb:1", "Путин В."))).ops == [
        ("hide", {"keys": ["kb:1"]})]


def test_hide_table_by_mention_is_hide_not_search():
    s = st(("kb:1", "X"), views=[AGG])
    assert route("скрой таблицу", ["table:agg:c1:h"], s).ops == [
        ("hide", {"keys": ["table:agg:c1:h"]})]


def test_table_filter_values():
    s = st(("kb:1", "X"), views=[AGG])
    (_, payload), = route("таблицей только 22 и 3389", ["agg:c1:h"], s).ops
    assert payload["view"]["filter"] == {"*": ["22", "3389"]}
    assert "агрегат" in route("таблицей", ["kb:1"], s).reply
    assert "@" in route("таблицей только 22", [], s).reply


def test_show_with_mention_and_text_is_search():
    s = st(("kb:1", "X"))
    assert route("покажи", ["kb:1"], s).ops == [("show", {"keys": ["kb:1"]})]
    assert route("покажи связи", ["kb:1"], s) == Search("покажи связи")


def test_open_and_stop():
    s = st(("kb:1", "X"))
    assert route("открой Росатом/Китай", [], s).open_query == "Росатом/Китай"
    assert is_stop("стоп") and is_stop("Останови.") and not is_stop("стоп-кран в поездах")
