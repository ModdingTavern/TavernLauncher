# Bump this with every release you publish to
# github.com/ModdingTavern/TavernLauncher/releases (tag it vX.Y.Z to match).
# This is the ONE file set_version.py patches for the client build --
# kept separate from launcher_window.py specifically so patching the
# version never risks touching (or needing to parse around) any other code.
APP_VERSION = "1.8.5"

# The subfolder this app occupies inside the release zip
# (TavernLauncher-vX.Y.Z.zip contains /Client and /Server side by side) --
# used by the self-updater to know which part of the zip is "ours".
UPDATE_APP_FOLDER = "Client"
