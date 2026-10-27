# Third-party components

Kubemap's own source code and artwork are distributed under the [MIT license](LICENSE). Each dependency keeps its own license. The MIT notice alone does not describe the terms of an assembled desktop distribution.

## Desktop

The desktop group uses `pywebview[pyside6]`, QtPy and PySide6. PyQt is not part of the supported build. PySide6/Shiboken and the Qt modules used by Kubemap provide an LGPLv3 licensing option. Qt WebEngine also contains Chromium and third-party components with their own notices.

- [Qt for Python licensing and notices](https://doc.qt.io/qtforpython-6/licenses.html)
- [Qt licensing](https://doc.qt.io/qt-6/licensing.html)
- [Qt WebEngine third-party licenses](https://doc.qt.io/qt-6/qtwebengine-licensing.html)
- [PySide/Shiboken source releases](https://download.qt.io/official_releases/QtForPython/)
- [Qt source releases](https://download.qt.io/official_releases/qt/)
- [Qt for Python source repository](https://code.qt.io/cgit/pyside/pyside-setup.git/)
- [Qt WebEngine source repository](https://code.qt.io/cgit/qt/qtwebengine.git/)

Versions are locked in `uv.lock`. Exact upstream source archive links for this release are recorded in [SOURCES.txt](packaging/licenses/SOURCES.txt). The build copies the installed dependency versions, metadata, available license/copyright/notice files, and bundled JavaScript license files into `/usr/share/doc/kubemap/third-party/`. It also supplies the GPLv3 and LGPLv3 texts under that directory. Chromium's embedded notices remain in the Qt WebEngine resources shipped with its libraries.

The PyInstaller `onedir` layout keeps shared libraries as separate files under `/opt/kubemap/`. Users may replace compatible LGPL components or rebuild the application with modified versions; Kubemap imposes no additional restriction on those activities or on debugging such modifications. Keep these notices with redistributed binaries and provide the corresponding dependency sources required by their licenses. The upstream links identify where source releases can be obtained; an upstream URL is not a substitute for a distributor's own source-provision obligations.

When publishing a desktop binary, attach `kubemap_0.1.0_source.tar.gz` beside the `.deb` and preserve the source references and notices. To rebuild, use the checked-out source version, the lockfiles and the instructions in README.md. Install the output under a location you control if you want to experiment with replacement libraries. Third-party sources and modifications are governed by their respective licenses, rather than Kubemap's MIT license.

## Web

Vue, Vuetify, Vue Flow, xterm.js and the other bundled frontend dependencies are listed in `web/package-lock.json`. Their available license notices are collected during desktop packaging. Development tools retain their own licenses too; they are not covered by Kubemap's MIT license.
