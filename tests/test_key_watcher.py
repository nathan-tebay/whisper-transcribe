"""Tests for key_watcher module."""
from unittest.mock import MagicMock, patch
from evdev import ecodes
from src.whisper_hotkey.key_watcher import find_keyboard_device, KeyWatcher


def test_find_keyboard_device_returns_none_when_no_devices():
    with patch("evdev.list_devices", return_value=[]):
        result = find_keyboard_device()
    assert result is None


def test_find_keyboard_device_finds_scroll_lock_capable():
    mock_dev = MagicMock()
    mock_dev.path = "/dev/input/event0"
    mock_dev.capabilities.return_value = {ecodes.EV_KEY: [ecodes.KEY_SCROLLLOCK]}
    with patch("evdev.list_devices", return_value=["/dev/input/event0"]):
        with patch("evdev.InputDevice", return_value=mock_dev):
            result = find_keyboard_device()
    assert result == mock_dev


def test_find_keyboard_device_closes_non_matching_devices():
    mock_dev = MagicMock()
    mock_dev.capabilities.return_value = {ecodes.EV_KEY: [ecodes.KEY_A]}  # no Scroll Lock
    with patch("evdev.list_devices", return_value=["/dev/input/event0"]):
        with patch("evdev.InputDevice", return_value=mock_dev):
            result = find_keyboard_device()
    assert result is None
    mock_dev.close.assert_called_once()


def test_key_watcher_calls_on_press_on_key_down():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = ecodes.EV_KEY
    mock_event.code = ecodes.KEY_SCROLLLOCK
    mock_event.value = 1  # key down
    watcher.handle_event(mock_event)
    on_press.assert_called_once()
    on_release.assert_not_called()


def test_key_watcher_calls_on_release_on_key_up():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = ecodes.EV_KEY
    mock_event.code = ecodes.KEY_SCROLLLOCK
    mock_event.value = 0  # key up
    watcher.handle_event(mock_event)
    on_release.assert_called_once()
    on_press.assert_not_called()


def test_key_watcher_ignores_autorepeat():
    """value=2 (autorepeat) must NOT trigger on_press — critical for hold-to-talk."""
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = ecodes.EV_KEY
    mock_event.code = ecodes.KEY_SCROLLLOCK
    mock_event.value = 2  # autorepeat
    watcher.handle_event(mock_event)
    on_press.assert_not_called()
    on_release.assert_not_called()


def test_key_watcher_ignores_other_keys():
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = ecodes.EV_KEY
    mock_event.code = ecodes.KEY_A
    mock_event.value = 1
    watcher.handle_event(mock_event)
    on_press.assert_not_called()
    on_release.assert_not_called()


def test_key_watcher_ignores_non_key_event_type():
    """Non-EV_KEY events (e.g. EV_SYN) with matching code must be ignored."""
    on_press = MagicMock()
    on_release = MagicMock()
    watcher = KeyWatcher(device=MagicMock(), keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    mock_event = MagicMock()
    mock_event.type = ecodes.EV_SYN  # not EV_KEY
    mock_event.code = ecodes.KEY_SCROLLLOCK
    mock_event.value = 1
    watcher.handle_event(mock_event)
    on_press.assert_not_called()
    on_release.assert_not_called()


def test_key_watcher_run_raises_on_grab_failure():
    on_press = MagicMock()
    on_release = MagicMock()
    mock_device = MagicMock()
    mock_device.path = "/dev/input/event0"
    mock_device.grab.side_effect = OSError(16, "Device or resource busy")
    watcher = KeyWatcher(device=mock_device, keycode=ecodes.KEY_SCROLLLOCK,
                         on_press=on_press, on_release=on_release)
    try:
        watcher.run()
        assert False, "Expected OSError"
    except OSError as e:
        assert "Failed to grab device" in str(e)
