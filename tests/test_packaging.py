import importlib.util
import json
import runpy
import sys
from types import ModuleType
import pytest
from importlib.metadata import Distribution
from pathlib import Path


def build_module():
    path = Path(__file__).resolve().parents[1] / "packaging" / "build_deb.py"
    spec = importlib.util.spec_from_file_location("build_deb", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_distribution_notices_include_python_and_bundled_frontend_licenses(tmp_path, monkeypatch):
    module = build_module()
    metadata = tmp_path / "fixture-1.0.dist-info"
    (metadata / "licenses").mkdir(parents=True)
    (metadata / "METADATA").write_text("Metadata-Version: 2.4\nName: fixture\nVersion: 1.0\nLicense-Expression: BSD-3-Clause\n")
    (metadata / "licenses" / "LICENSE").write_text("Fixture copyright and redistribution conditions")
    (metadata / "RECORD").write_text("fixture-1.0.dist-info/licenses/LICENSE,,\n")
    frontend = tmp_path / "web" / "node_modules" / "component"
    frontend.mkdir(parents=True)
    (frontend / "LICENSE").write_text("Component copyright and permission")
    (tmp_path / "web" / "package-lock.json").write_text(json.dumps({"packages": {"node_modules/component": {"version": "2.0", "license": "MIT"}}}))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "distributions", lambda: [Distribution.at(metadata)], raising=False)
    destination = tmp_path / "notices"
    module.collect_licenses(destination)
    text = "\n".join(p.read_text() for p in destination.rglob("*") if p.is_file())
    assert "fixture 1.0" in text
    assert "BSD-3-Clause" in text
    assert "Fixture copyright and redistribution conditions" in text
    assert "Component copyright and permission" in text
    assert "component 2.0" in text
    assert (destination / "python" / "fixture-1.0" / "METADATA.txt").read_text() == (metadata / "METADATA").read_text()


def test_packaging_excludes_unused_qt_modules_with_additional_license_requirements():
    module = build_module()
    excluded = module.excluded_qt_modules(["QtCore", "QtGui", "QtWebEngineCore", "QtWebEngineWidgets", "QtDataVisualization", "QtCharts", "QtGraphs", "QtQuick"])
    assert excluded == ["PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtQuick"]


def test_qt_gui_hook_keeps_desktop_input_plugins_and_skips_virtual_keyboard(monkeypatch):
    qt = ModuleType("PyInstaller.utils.hooks.qt")
    qt.add_qt6_dependencies = lambda _: (["PySide6.QtCore"], [("/qt/plugins/libqtvirtualkeyboardplugin.so", "platforminputcontexts"), ("/qt/plugins/libcomposeplatforminputcontextplugin.so", "platforminputcontexts")], [])
    for name in ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks.qt", qt)
    path = Path(__file__).resolve().parents[1] / "packaging" / "hooks" / "hook-PySide6.QtGui.py"
    hook = runpy.run_path(str(path))
    assert hook["binaries"] == [("/qt/plugins/libcomposeplatforminputcontextplugin.so", "platforminputcontexts")]
    assert hook["hiddenimports"] == ["PySide6.QtCore"]


def test_unwanted_qt_libraries_prevent_building_a_distribution(tmp_path):
    module = build_module()
    (tmp_path / "libQt6Quick.so.6").touch()
    module.verify_qt_libraries(tmp_path)
    (tmp_path / "libQt6VirtualKeyboard.so.6").touch()
    with pytest.raises(RuntimeError, match="VirtualKeyboard"):
        module.verify_qt_libraries(tmp_path)
