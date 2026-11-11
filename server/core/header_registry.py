import os

from tavern_shared.orderable_registry import OrderableRegistry
from tavern_shared.paths import _tavern_data_dir

_registry = OrderableRegistry(os.path.join(_tavern_data_dir(), "server_header_order.json"))


def register_header_button(key, icon_text, command_attr=None, label=None, built_in=False,
                           command=None, after=None):
    """A button in the Server launcher's header. command(launcher) runs on a
    click. The older form names a method instead (command_attr), which the
    addon then had to monkeypatch onto ServerLauncher; it still works.
    after= puts it right after another header button's key. built_in=True
    only affects the default order (core buttons first) before a user saves
    their own.
    """
    if command is None and command_attr is None:
        raise ValueError("register_header_button needs command or command_attr")
    _registry.register(key, built_in=built_in, icon_text=icon_text, command_attr=command_attr,
                       command=command, after=after, label=label or icon_text)


def ordered_buttons():
    return _registry.ordered_items()


def registry():
    return _registry
