"""Tests for daemon on_release() routing logic."""
from unittest.mock import MagicMock, patch, call
import src.whisper_hotkey.daemon as daemon


def _make_mocks():
    """Patch all daemon module-level singletons and collaborators."""
    recorder  = MagicMock()
    notify    = MagicMock()
    type_text = MagicMock(return_value=True)
    run_cmd   = MagicMock(return_value=True)
    return recorder, notify, type_text, run_cmd


def _run_release(text, recorder, notify, type_text, run_cmd, duration=1.0):
    recorder.stop.return_value = duration
    with patch.object(daemon, "recorder",    recorder), \
         patch.object(daemon, "transcriber", MagicMock(transcribe=MagicMock(return_value=text))), \
         patch.object(daemon, "notify",      notify), \
         patch.object(daemon, "type_text",   type_text), \
         patch.object(daemon, "run_command", run_cmd):
        daemon.on_release()


# ---------------------------------------------------------------------------
# Normal text routing
# ---------------------------------------------------------------------------

def test_normal_text_routes_to_type_text():
    recorder, notify, type_text, run_cmd = _make_mocks()
    _run_release("hello world", recorder, notify, type_text, run_cmd)
    type_text.assert_called_once_with("hello world")
    run_cmd.assert_not_called()


# ---------------------------------------------------------------------------
# run command trigger
# ---------------------------------------------------------------------------

def test_run_command_trigger_calls_run_command():
    recorder, notify, type_text, run_cmd = _make_mocks()
    _run_release("run command open vs code", recorder, notify, type_text, run_cmd)
    run_cmd.assert_called_once_with("open vs code")
    type_text.assert_not_called()


def test_run_command_trigger_case_insensitive():
    recorder, notify, type_text, run_cmd = _make_mocks()
    _run_release("RUN COMMAND open vs code", recorder, notify, type_text, run_cmd)
    run_cmd.assert_called_once_with("open vs code")
    type_text.assert_not_called()


def test_run_command_trigger_strips_extra_whitespace():
    recorder, notify, type_text, run_cmd = _make_mocks()
    _run_release("run command   open vs code", recorder, notify, type_text, run_cmd)
    run_cmd.assert_called_once_with("open vs code")


def test_run_command_failure_notifies_critical():
    recorder, notify, type_text, run_cmd = _make_mocks()
    run_cmd.return_value = False
    _run_release("run command open vs code", recorder, notify, type_text, run_cmd)
    # Find the critical notification call
    critical_calls = [c for c in notify.call_args_list if c.kwargs.get("urgency") == "critical"]
    assert critical_calls, "Expected a critical urgency notification on failure"


# ---------------------------------------------------------------------------
# False-positive prevention
# ---------------------------------------------------------------------------

def test_run_commands_are_useful_does_not_trigger():
    """'run command' without trailing space must not trigger."""
    recorder, notify, type_text, run_cmd = _make_mocks()
    _run_release("run commands are useful", recorder, notify, type_text, run_cmd)
    run_cmd.assert_not_called()
    type_text.assert_called_once_with("run commands are useful")
