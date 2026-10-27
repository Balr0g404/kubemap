from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# The optional virtual keyboard has separate licensing and is not used by Kubemap.
binaries = [entry for entry in binaries if "virtualkeyboard" not in entry[0].lower()]
