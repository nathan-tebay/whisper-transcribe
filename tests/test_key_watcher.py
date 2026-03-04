"""Tests for key_watcher module."""
from unittest.mock import MagicMock, patch
from src.whisper_hotkey.key_watcher import find_keyboard_device, KeyWatcher


def test_find_keyboard_device_returns_none_when_no_devices():
    with patch("evdev.list_devices", return_value=[]):
        result = find_keyboard_device()
    assert result is None


def test_find_keyboard_device_finds_scroll_lock_capable():
    mock_dev = MagicMock()
    mock_dev.path = "/dev/input/event0"
    mock_dev.capabilities.return_value = {1: [70]}  # KEY_SCROLLLOCK = 70
    with patch("evdev.list_devices", return_value=["/dev/input/event0"]):
        with patch("evdev.InputDevice", return_value=mock_dev):
            result = find_keyboard_device()
    assert result == mock_dev


def test_key_watcher_calls_on_press_on_key_down():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1   # EV_KEY
    mock_event.code = 70  # KEY_SCROLLLOCK
    mock_event.value = 1  # key down
    watcher.handle_event(mock_event)
    on_press.assert_called_once()
    on_release.assert_not_called()


def test_key_watcher_calls_on_release_on_key_up():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1
    mock_event.code = 70
    mock_event.value = 0  # key up
    watcher.handle_event(mock_event)
    on_release.assert_called_once()
    on_press.assert_not_called()


def test_key_watcher_ignores_other_keys():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=70,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = 1
    mock_event.code = 30  # KEY_A, not our key
    mock_event.value = 1
    watcher.handle_event(mock_event)
    on_press.assert_not_called()
    on_release.assert_not_called()
