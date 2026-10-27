"""Construit un .deb autonome, sans installation système ni connexion au cluster."""

import os
import json
from importlib.metadata import distributions
import platform
import pkgutil
from importlib.util import find_spec
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for package in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name, version = package.metadata["Name"], package.version
        target = destination / "python" / f"{name}-{version}"
        target.mkdir(parents=True, exist_ok=True)
        license = package.metadata.get("License-Expression") or package.metadata.get("License") or "See package notices"
        links = package.metadata.get_all("Project-URL") or []
        inventory.append(f"{name} {version}\n{license}\n" + "\n".join(links))
        (target / "METADATA.txt").write_text(package.read_text("METADATA") or package.read_text("PKG-INFO") or f"Name: {name}\nVersion: {version}\n", encoding="utf-8")
        for entry in package.files or []:
            if ".." in entry.parts or not any(word in entry.name.lower() for word in ("license", "licence", "copying", "copyright", "notice")):
                continue
            source = Path(package.locate_file(entry))
            if source.is_file():
                output = target / str(entry)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text())
    for path, package in lock["packages"].items():
        if not path or package.get("dev"):
            continue
        source = ROOT / "web" / path
        if not source.is_dir():
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        inventory.append(f"{name} {package['version']}\n{package.get('license', 'See package notices')}")
        target = destination / "javascript" / name
        target.mkdir(parents=True, exist_ok=True)
        for entry in source.iterdir():
            if entry.is_file() and entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE", "COPYRIGHT")):
                shutil.copy2(entry, target / entry.name)
    (destination / "INDEX.txt").write_text("\n\n".join(inventory) + "\n", encoding="utf-8")
    if (ROOT / "packaging" / "licenses").is_dir():
        shutil.copytree(ROOT / "packaging" / "licenses", destination / "qt", dirs_exist_ok=True)


def excluded_qt_modules(names):
    used = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtWebChannel", "QtWebEngineCore", "QtWebEngineWidgets", "QtOpenGL", "QtOpenGLWidgets", "QtPrintSupport"}
    return ["PySide6." + name for name in sorted(names) if name.startswith("Qt") and name not in used]


def verify_qt_libraries(directory):
    extra = ("QtCharts", "QtDataVisualization", "QtGraphs", "QtQuick3D", "QtVirtualKeyboard")
    unexpected = sorted({path.name for path in directory.rglob("*") if path.is_file() and any(name in path.name.replace("Qt6", "Qt") for name in extra)})
    if unexpected:
        raise RuntimeError("Unexpected optional Qt modules: " + ", ".join(unexpected))


def main():
    for command in ("npm", "dpkg", "dpkg-deb"):
        if not shutil.which(command):
            raise SystemExit(f"Commande requise : {command}")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    output = ROOT / "dist" / f"kubemap_{version}_{arch}.deb"
    output.parent.mkdir(exist_ok=True)
    subprocess.run(["npm", "run", "build", "--prefix", "web"], cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix="kubemap-deb-") as directory:
        stage = Path(directory)
        package = stage / "package"
        modules = [m.name for m in pkgutil.iter_modules(find_spec("PySide6").submodule_search_locations)]
        exclusions = [arg for name in excluded_qt_modules(modules) for arg in ("--exclude-module", name)]
        subprocess.run([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--name", "kubemap", "--onedir", "--paths", str(ROOT),
            "--distpath", str(package / "opt"),
            "--workpath", str(stage / "work"), "--specpath", str(stage),
            "--add-data", f"{ROOT / 'web' / 'dist'}:web/dist",
            "--add-data", f"{ROOT / 'web' / 'public'}:web/public",
            "--add-data", f"{ROOT / 'kubemap' / 'layers.yaml'}:kubemap",
            "--collect-data", "webview", "--collect-submodules", "uvicorn",
            "--hidden-import", "webview.platforms.qt",
            "--additional-hooks-dir", str(ROOT / "packaging" / "hooks"),
            *exclusions,
            str(ROOT / "packaging" / "desktop_entry.py"),
        ], cwd=ROOT, env={**os.environ, "QT_API": "pyside6", "PYINSTALLER_CONFIG_DIR": str(stage / "cache")}, check=True)
        verify_qt_libraries(package / "opt")
        binary = package / "opt" / "kubemap" / "kubemap"
        # Ce contrôle ne charge aucun kubeconfig et ne contacte aucun cluster.
        help_text = subprocess.check_output([str(binary), "--help"], text=True)
        if "--desktop" not in help_text:
            raise RuntimeError("Le binaire desktop n’a pas passé le contrôle de démarrage.")
        commands = package / "usr" / "bin"
        commands.mkdir(parents=True)
        launcher = commands / "kubemap"
        launcher.write_text('#!/bin/sh\nexec /opt/kubemap/kubemap "$@"\n')
        launcher.chmod(0o755)
        applications = package / "usr" / "share" / "applications"
        applications.mkdir(parents=True)
        shutil.copy2(ROOT / "packaging" / "kubemap.desktop", applications)
        documentation = package / "usr" / "share" / "doc" / "kubemap"
        documentation.mkdir(parents=True)
        shutil.copy2(ROOT / "LICENSE", documentation / "copyright")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", documentation / "THIRD_PARTY_NOTICES.md")
        collect_licenses(documentation / "third-party")
        for size in (256, 512):
            raster = package / "usr" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
            raster.mkdir(parents=True)
            shutil.copy2(ROOT / "packaging" / "icons" / f"kubemap-{size}.png", raster / "kubemap.png")
        control = package / "DEBIAN"
        control.mkdir()
        libc = platform.libc_ver()[1]
        (control / "control").write_text(
            f"Package: kubemap\nVersion: {version}\nArchitecture: {arch}\n"
            "Maintainer: Kubemap <kubemap@localhost>\nSection: utils\nPriority: optional\n"
            f"Depends: libc6 (>= {libc}), libstdc++6, libgcc-s1, libgl1, libegl1, "
            "libxkbcommon0, libdbus-1-3, libnss3, libasound2t64 | libasound2, "
            "libxcomposite1, libxdamage1, libxrandr2, libxtst6, libxcb-cursor0, "
            "libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, "
            "libxcb-xinerama0, libxcb-xkb1, libxkbcommon-x11-0\n"
            "Description: Cartographie locale et en direct de Kubernetes\n"
            " Interface desktop Kubemap avec Python et Qt embarqués.\n"
        )
        subprocess.run([
            "dpkg-deb", "--build", "--root-owner-group", "-Zzstd",
            str(package), str(output),
        ], check=True)
    print(f"Paquet créé : {output}")


if __name__ == "__main__":
    main()
