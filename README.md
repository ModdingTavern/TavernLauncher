# TavernLauncher
Launchers for client/server management of A Township Tale


## Prefabulator add-on

Enable Prefabulator in the client Addons window and restart the launcher. Its main-launcher button connects the in-game editor through the existing remote console. The connection follows the server selected in the Client launcher; moderator codes select their own server there too. Optionally save the access token using Windows account encryption to connect automatically when launching the same server. All editing happens in game (F1).

Follow [the player setup instructions](addons/prefab_editor/START%20HERE.txt). Source checkouts download a checksum-pinned runtime on first use. The [full player package and server mod](https://github.com/calebv2/ATT-Prefab-Editor/releases/tag/prefabulator-v1.0.23) and [mod source](https://github.com/calebv2/ATT-Prefab-Editor/tree/prefabulator-v1.0.23) are published separately. The server needs PrefabEditorCore.dll and a working Tavern remote console. For one shared server/player game folder, tick the shared-folder option to install both DLLs from the pinned all-in-one runtime; stop both processes before updating. This choice is remembered per game folder. If the server runs on your playing computer but you join through a public or LAN address, select the local-console option to pair that game address with console localhost.

Owners can create named personal moderator codes with allowed tabs from Manage Admin Access in Prefabulator. Revocation disconnects active personal sessions; the server enforces each profile on every command. Anyone given the owner console token has full console access, and one person's access cannot be revoked while they still know that shared token. Give other admins personal tokens instead. Player mod 2.3.8 adds Build > Strings for local string files/folders and Prefabs wording; install/update the player mod after updating the add-on. Server core 1.6.7 fixes duplicate owner WebSocket command execution. Restart the server after updating it. The owner must explicitly grant Console to existing moderators; it allows broad native server commands.

Release 1.0.7 fixes linked teleporter timing in server core 1.6.1: destination loading starts on contact and player movement waits for the platform animation to finish.
