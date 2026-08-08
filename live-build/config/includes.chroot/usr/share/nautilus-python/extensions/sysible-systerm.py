# Adds "Open in SysTerm" to the Nautilus right-click menu (on folders and on the
# folder background), launching SysTerm in that directory.
import gi

# Bookworm's Nautilus is GTK4 (Nautilus 4.0); pin the version so the import
# resolves regardless of loader defaults, falling back to 3.0 on older systems.
for _ver in ("4.0", "3.0"):
    try:
        gi.require_version("Nautilus", _ver)
        break
    except (ValueError, AttributeError):
        continue

from gi.repository import Nautilus, GObject
import subprocess


def _launch(path):
    for cmd in (["systerm"], ["x-terminal-emulator"]):
        try:
            subprocess.Popen(cmd, cwd=path)
            return
        except FileNotFoundError:
            continue


class SysTermExtension(GObject.GObject, Nautilus.MenuProvider):
    def _open(self, _menu, path):
        _launch(path)

    def _item(self, name, path):
        it = Nautilus.MenuItem(name=name, label="Open in SysTerm",
                               tip="Open a SysTerm terminal here")
        it.connect("activate", self._open, path)
        return it

    # Right-click on a selected folder
    def get_file_items(self, *args):
        files = args[-1]
        if len(files) != 1 or not files[0].is_directory():
            return []
        loc = files[0].get_location().get_path()
        return [self._item("SysTerm::OpenFolder", loc)] if loc else []

    # Right-click on empty space inside a folder
    def get_background_items(self, *args):
        folder = args[-1]
        loc = folder.get_location().get_path()
        return [self._item("SysTerm::OpenBackground", loc)] if loc else []
