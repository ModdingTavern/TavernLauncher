# TavernLauncher
Launchers for client/server management of A Township Tale


## Prefabulator add-on

Enable Prefabulator in the client Addons window and restart the launcher. Its main-launcher button connects the in-game editor through the existing remote console. The server address is remembered; optionally save their access token using Windows account encryption to connect automatically when launching the same server. All editing happens in game (F1).

Follow [the player setup instructions](addons/prefab_editor/START%20HERE.txt). Source checkouts download a checksum-pinned runtime on first use. The [full player package and server mod](https://github.com/calebv2/ATT-Prefab-Editor/releases/tag/prefabulator-v1.0.7) and [mod source](https://github.com/calebv2/ATT-Prefab-Editor/tree/prefabulator-v1.0.7) are published separately. The server needs PrefabEditorCore.dll and a working Tavern remote console.

Owners can create named personal admin tokens with allowed tabs from Manage Admin Access in Prefabulator. Revocation disconnects active sessions; the server enforces each profile on every command. Both player and server packages must be updated to 1.0.6.

Release 1.0.7 fixes linked teleporter timing in server core 1.6.1: destination loading starts on contact and player movement waits for the platform animation to finish.
