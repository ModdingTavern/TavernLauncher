# Joining a public server

If you have no interest in hosting a server for yourself, this guide will cover simply joining an existing server.

## Getting the files for The Modding Tavern

The connection towards private servers is done via TavernLauncher, a custom launcher which will connect you towards
private servers hosted via either TavernLib or TavernLauncher.
TavernLauncher comes in two versions: client and server.

For this step, you need the client version. <br>
The latest OFFICIAL version of TavernLauncher can be gotten from this repository: <br>
<https://github.com/ModdingTavern/TavernLauncher/releases>

Scroll down to the assets section, and download the client version by simply clicking on the line looking like this: <br>
`TavernLauncher-Client-vX.Y.Z.zip`

This will download a .zip file to your computer. Right click it and extract it.
You now have all the files needed for this step.

## Running TavernLauncher (Client)

Open the folder you extracted in the previous step, you will see the following files:

```
TavernLauncher-Client-vX.Y.Z
├─ addons
├─ Patch
├─ Instructions.txt
└─ TavernLauncher - Client.exe
```

Simply double click the .exe and the application will open.

If you get questions about your firewall regarding opening the application, choose to allow the program.
Some antivirus/firewalls may flag the application as a potential threat (rightfully so since it's a homebrew application in the end),
but since we are open sourced you can see exactly what the application does and how it's built by looking inside of the actual GitHub
repository.

## Pointing TavernLauncher to your game

In order for TavernLauncher to be able to make changes to your game, it has to know where it lives! <br>
Click the "Browse" button and select the .exe file in this location: <br>
`C:\Games\Alta\A Township Tale\A Township Tale.exe`

If you installed the game in another directory, point it to the .exe in that folder!

## Patching the game

To ensure private servers were possible, a few patches and mods are needed to your base game files. <br>
TavernLauncher has this process built-in to simplify it as much as possible for you. <br>

Inside of the application, you will notice two buttons are flashing: <br>
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

### Username

Fill in a username. This is the identity under which you will be known on whichever server you are connecting to.
Good to know: choosing your username on one server does not mean it is automatically the same on another server!
Each servers tracks their own information.

### Platform

Choose what hardware you're playing on. Select Quest for any Meta/Oculus hardware or SteamVR for all others.
"Fly" is a special gamemode that requires certain server privileges in order to work. More on that in the server hosting section.

## Joining a server

Now that your game is ready for joining a server, all you need to do is select a server and join!

### Community Servers

For your convenience we offer a service for all server hosters to publish their server to our own hosted API.
This makes it easier for the playerbase to find your server.
Please note that this is an optional service that may disappear at some point in the future - but it is important to note that this
is not required to run the servers at all.

Simply click "Community Servers" to open the list of published servers.
Select any entry in the list and click "Connect" in the bottom right.
This will fill in all the needed server information automatically.
Simply click "Join Server" and the game will launch!

### Manual input

#### Self Hosting

If you are hosting the server yourself, simply leave the "Destination" field empty.
Click "Join Server" and it will automatically attempt to join your own server (if it's running).

#### Gather the server information

If your friend is hosting the server, he has to give you the following information: <br>
- The public IP of the machine hosting his server

Simply grab this IP (e.g. `154.25.48.65`) and put it into the "Destination" field on the client. <br>
Click "Join Server" to join it.

## Conclusion

That's it, you should now be in-game. <br>
If you somehow ended up in the "main menu" of Township Tale and not directly into the server, that means something has gone wrong.
Please refer to the [FAQ](page:faq) for assistance in this.
