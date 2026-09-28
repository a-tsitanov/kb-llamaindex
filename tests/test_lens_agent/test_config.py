import pytest
from pydantic import ValidationError

from src.lens_agent.config import AgentSettings, McpEntry


def board(name="board", enabled=True):
    return McpEntry(name=name, url="http://lens/mcp/mcp", role="board", enabled=enabled)


def test_board_entry_must_be_named_board():
    # the prompt names the board tools board_* — the tool prefix is the entry name
    with pytest.raises(ValidationError, match="must be named 'board'"):
        AgentSettings(mcp=[board("lens")])
    assert AgentSettings(mcp=[board(), board("old", enabled=False)]).board().name == "board"


def test_only_one_enabled_board():
    with pytest.raises(ValidationError, match="one enabled board"):
        AgentSettings(mcp=[board(), board("board")])


def test_no_board_is_allowed_at_config_time():
    assert AgentSettings(mcp=[McpEntry(name="kb", url="http://kb/mcp")]).board() is None
