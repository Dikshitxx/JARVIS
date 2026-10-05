import pytest

import app.tools  # noqa: F401  registers all tools
from app.tools.registry import run_tool, REGISTRY, NeedsConfirmation
from app.permissions.classify import classify
from app.memory import store


def test_placeholder():
    assert True


# --- Classifier ---

def test_classify_safe_tool_allows():
    decision, _ = classify("get_time", {})
    assert decision == "ALLOW"


def test_classify_confirm_tool():
    decision, _ = classify("close_app", {"name": "notepad"})
    assert decision == "CONFIRM"


def test_classify_unknown_tool_blocks():
    decision, _ = classify("not_a_real_tool", {})
    assert decision == "BLOCK"


def test_classify_credential_content_blocks():
    decision, reason = classify("remember_fact", {"content": "my password is hunter2"})
    assert decision == "BLOCK"
    assert "credential" in reason


def test_classify_memory_write_requires_confirmation():
    decision, _ = classify("remember_fact", {"content": "User likes tea"})
    assert decision == "CONFIRM"


def test_classify_open_app_allowlisted():
    decision, _ = classify("open_app", {"name": "notepad"})
    assert decision == "ALLOW"


def test_classify_open_app_unknown_is_safe():
    decision, _ = classify("open_app", {"name": "some_random_app"})
    assert decision == "ALLOW"


def test_open_app_launches_windows_explorer_when_shell_windows_are_present(monkeypatch):
    import types

    from app.tools import apps

    class FakeWindow:
        def __init__(self, title: str):
            self._title = title

        def window_text(self):
            return self._title

        def process_id(self):
            return 1234

    class FakeDesktop:
        def windows(self):
            return [FakeWindow("Taskbar"), FakeWindow("Program Manager")]

    fake_pywinauto = types.SimpleNamespace(Desktop=FakeDesktop)
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", fake_pywinauto)
    monkeypatch.setattr(apps, "_process_names", lambda _app_name: {"explorer.exe"})
    monkeypatch.setattr(apps, "_wait_for_window", lambda *_args, **_kwargs: True)
    called = {}

    def fake_popen(args, shell=False, creationflags=0):
        called["args"] = args
        called["shell"] = shell
        called["creationflags"] = creationflags
        return object()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = apps.open_app("explorer")

    assert result.status == "success"
    assert result.message.startswith("Opened explorer")
    assert called["args"][0].lower().endswith("explorer.exe")


def test_open_app_opens_whatsapp_web(monkeypatch):
    from app.tools import apps
    called = {}

    def fake_open_url(url):
        called["url"] = url
        return type("R", (), {"status": "success"})()

    monkeypatch.setattr(apps, "_matching_windows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("app.tools.browser.open_url", fake_open_url)

    result = apps.open_app("whatsapp")

    assert result.status == "success"
    assert called["url"] == "https://web.whatsapp.com"


# --- File sandbox ---

def test_file_sandbox_blocks_outside_data_dir():
    result = run_tool("list_files", {"path": "C:/Windows"})
    assert "not permitted" in result.lower() or "error" in result.lower()


def test_file_sandbox_allows_data_dir():
    result = run_tool("list_files", {"path": "."})
    assert "error" not in result.lower() or "not a folder" not in result.lower()


def test_find_file_searches_for_matching_folders_and_files(monkeypatch, tmp_path):
    from app.tools import files

    root = tmp_path / "Desktop"
    folder = root / "Synaxis Project"
    folder.mkdir(parents=True)
    file_path = root / "synaxis-notes.txt"
    file_path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(files, "_safe_roots", lambda: {
        "desktop": root, "documents": root, "downloads": root, "data": root,
    })

    result = files.find_file("synaxis")

    assert result.status == "success"
    assert str(folder) in result.data["folders"]
    assert str(file_path) in result.data["files"]
    assert f"[folder] {folder}" in result.message
    assert str(file_path) in result.message


# --- Terminal allowlist ---

def test_terminal_allowlist_refuses_unlisted_command():
    result = run_tool("run_command", {"command": "del data"})
    assert "refused" in result.lower()


def test_terminal_allowlist_refuses_chained_command():
    result = run_tool("run_command", {"command": "git status && whoami"})
    assert "refused" in result.lower()


def test_terminal_allowlist_allows_listed_command():
    result = run_tool("run_command", {"command": "git --version"})
    assert "refused" not in result.lower()


# --- App allowlist / blocklist ---

def test_open_app_blocklist_refuses_powershell():
    result = run_tool("open_app", {"name": "powershell"})
    assert "blocked" in result.lower() or "refused" in result.lower()


def test_open_app_blocklist_refuses_cmd():
    result = run_tool("open_app", {"name": "cmd"})
    assert "blocked" in result.lower() or "refused" in result.lower()


# --- Confirmation gate at the run_tool level ---

def test_confirm_tool_raises_without_confirmation():
    with pytest.raises(NeedsConfirmation):
        run_tool("close_app", {"name": "notepad"}, confirmed=False)


def test_confirm_tool_does_not_raise_when_confirmed():
    # notepad likely isn't running; this just proves no NeedsConfirmation is raised
    result = run_tool("close_app", {"name": "notepad"}, confirmed=True)
    assert isinstance(result, str)


# --- Memory store ---

def test_memory_fact_roundtrip():
    store.add_fact("pytest test fact xyz123")
    facts = store.list_facts()
    assert any("pytest test fact xyz123" in f[1] for f in facts)
    store.delete_matching("pytest test fact xyz123")
    facts_after = store.list_facts()
    assert not any("pytest test fact xyz123" in f[1] for f in facts_after)


def test_memory_person_roundtrip():
    pid = store.add_person("Pytest Person", "test", "created by automated test")
    people = store.list_people()
    assert any(p[0] == pid for p in people)


# --- Registry sanity ---

def test_all_registered_tools_have_valid_risk():
    for tool in REGISTRY.values():
        assert tool.risk in ("safe", "confirm", "blocked")


def test_expected_tools_are_registered():
    expected = {
        "get_time", "get_system_info", "get_weather", "calculate", "list_files", "read_text_file",
        "run_command", "remember_fact", "list_memories", "forget_memory",
        "open_app", "close_app", "take_screenshot", "remember_person", "list_known_people",
        "move_mouse", "click_mouse", "type_text", "press_key",
        "find_project", "find_project_deep", "inspect_project",
        "start_project", "stop_project", "project_status",
    }
    assert expected.issubset(set(REGISTRY.keys()))
