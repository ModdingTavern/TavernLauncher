# Setting up a local server for yourself

Want to host your very own world and play on it locally in singleplayer? You've come to the right place.

## Getting the files for The Modding Tavern

The connection towards private servers is done via TavernLauncher, a custom launcher which will connect you towards
private servers hosted via either TavernLib or TavernLauncher.
TavernLauncher comes in two versions: client and server.

For this step, you need the server version.
The latest OFFICIAL version of TavernLauncher can be gotten from this repository:
<https://github.com/ModdingTavern/TavernLauncher/releases>

Scroll down to the assets section, and download the server version by simply clicking on the line looking like this:
`TavernLauncher-Server-vX.Y.Z.zip`

This will download a .zip file to your computer. Right click it and extract it.
You now have all the files needed for this step.

## Running TavernLauncher (Server)

Open the folder you extracted in the previous step, you will see the following files:

```
TavernLauncher-Server-vX.Y.Z
├─ addons
├─ Patch
├─ Instructions.txt
└─ TavernLauncher - Server.exe
```

Simply double click the .exe and the application will open.

If you get questions about your firewall regarding opening the application, choose to allow the program.
Some antivirus/firewalls may flag the application as a potential threat (rightfully so since it's a homebrew application in the end),
but since we are open sourced you can see exactly what the application does and how it's built by looking inside of the actual GitHub
repository.

## Pointing TavernLauncher to your game

In order for TavernLauncher to be able to make changes to your game, it has to know where it lives!
Click the "Browse" button and select the .exe file in this location: <br>
`C:\Games\Alta\A Township Tale\A Township Tale.exe`

If you installed the game in another directory, point it to the .exe in that folder!

## Patching the game

To ensure private servers were possible, a few patches and mods are needed to your base game files.
TavernLauncher has this process built-in to simplify it as much as possible for you.
If you've already done this by reading the previous guide for joining a server, you don't need to do this again.

Inside of the application, you will notice two buttons are flashing (if not patched already): <br>
- Patch <br>
- Mods

First, click "Patch". <br>
This will prepare your game files for allowing connections towards private servers by modding some code.

Second, click "Mods". <br>
This will open a mods window that contains the mods required to run the infrastructure of The Modding Tavern.
Click "Install" on each of the following in order:

- **MelonLoader** — This is the modding platform that will inject all the mods into your game, this is the base requirement for all changes. This is a 3rd party application not managed by us.
- **TavernLib** — This is the driving power behind The Modding Tavern and contains the needed bridges to restore private servers.
- **TavernVoice** - An optional but highly recommended mod that will allow proximity voice chat inside the game, since the official service was retired. It replaces CircuitsVoiceChat, which is no longer maintained, and removes it when installed. (Credits to [CircuitLord](https://github.com/CircuitLord))

That's it. If the buttons have stopped flashing you should be on the latest versions of everything that's needed.

## Essentials

### Game Port

Defaults to 1757, recommended to leave this as is unless you very specifically know what you are doing.

### Server Settings

Click the "Settings" button to start configuring your server.
Fill in the following fields: <br>
- Server Name <br>
- **Auto-reboot** (optional, but recommended) — Leaving a server up for long times can cause performance issues or connectivity issues. Recommended to turn this on to reboot every once in a while to prevent piling of problems.

### Players

Click the "Players" button to open the player management system. <br>
If you do not care about setting admin rights on your account and just want to play singleplayer, skip this whole section.

#### Players

Here you will be able to see every player that has connected to your server, together with their assigned userID.
Selecting any entry you are able to change their user ID manually, reset their authentication token, edit their roles or kick them from your server.

Recognized roles at this time are the following: <br>
- admin <br>
- mod <br>
- fly

Giving any of the above roles to a user will allow them to join your server with the "fly" gamemode, which is a flatscreen gamemode
that allows flying around in your world. More functionality will be created for this.

## Starting Your Server

Simply hit the "Open Server" button to start up your own server.
This will launch a background process that will handle the gameserver on its own.

You may get a popup from Windows or your firewall asking you if you want to allow connections for this application, select yes.
Not doing this means your firewall may prevent you from connecting.

## Conclusion

All done, your server is now ready and running.
Go ahead and connect to your server by following the "joining" section of this documentation.
