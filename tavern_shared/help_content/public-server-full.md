# Setting up a public server for yourself that others can join

Want to host your very own world and have your friends or random strangers join your server? Read this section!

## Getting the files for The Modding Tavern

The connection towards private servers is done via TavernLauncher, a custom launcher which will connect you towards
private servers hosted via either TavernLib or TavernLauncher.
TavernLauncher comes in two versions: client and server.

For this step, you need the server version. <br>
The latest OFFICIAL version of TavernLauncher can be gotten from this repository: <br>
<https://github.com/ModdingTavern/TavernLauncher/releases>

Scroll down to the assets section, and download the server version by simply clicking on the line looking like this: <br>
`TavernLauncher-Server-vX.Y.Z.zip` <br>

This will download a .zip file to your computer. Right click it and extract it. <br>
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
`C:\Games\Alta\A Township Tale\A Township Tale.exe` <br>

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
Click "Install" on each of the following in order: <br>

- **MelonLoader** — This is the modding platform that will inject all the mods into your game, this is the base requirement for all changes. This is a 3rd party application not managed by us.
- **TavernLib** — This is the driving power behind The Modding Tavern and contains the needed bridges to restore private servers.
- **TavernVoice** - An optional but highly recommended mod that will allow proximity voice chat inside the game, since the official service was retired. It replaces CircuitsVoiceChat, which is no longer maintained, and removes it when installed. (Credits to [CircuitLord](https://github.com/CircuitLord))

That's it. If the buttons have stopped flashing you should be on the latest versions of everything that's needed.

## Essentials

### Game Port

Defaults to 1757, recommended to leave this as is unless you very specifically know what you are doing.

### Server Settings

Click the "Settings" button to start configuring your server. <br>
Fill in the following fields: <br>
- Server Name
- Max Players
- Password (optional)
- **Whitelist** (optional) — if enabled only players in the 'Players - Whitelist' section can join your server. Players will also be able to apply to your server.
- **Community server browser listing** (optional) — if enabled your server will be known to other players in the server list.
- **5 IP per account limit** (optional) — if enabled players won't be able to create more than 5 characters on your server.
- **Region** (optional) — but will be displayed if you also enabled the community server browser listing.
- **Public Hostname** (optional) — you can fill in a DNS name here to make your server appear as that name IF your server resolves to the same IP as the DNS name.
- **Auto-reboot** (optional, but recommended) — Leaving a server up for long times can cause performance issues or connectivity issues. Recommended to turn this on to reboot every once in a while to prevent piling of problems.

### Players

Click the "Players" button to open the player management system.

#### Players

Here you will be able to see every player that has connected to your server, together with their assigned userID.
Selecting any entry you are able to change their user ID manually, reset their authentication token, edit their roles or kick them from your server.

Recognized roles at this time are the following: <br>
- admin <br>
- mod <br>
- fly

Giving any of the above roles to a user will allow them to join your server with the "fly" gamemode, which is a flatscreen gamemode
that allows flying around in your world. More functionality will be created for this.

#### Blacklist

Blacklist any usernames/IP's that you don't want joining your server here.

#### Whitelist

Whitelist any username/IP's that you want joining your server here.

#### Whitelist Applications

Any players that applied to your server can be viewed/approved from this window.

## Starting Your Server

Simply hit the "Open Server" button to start up your own server.
This will launch a background process that will handle the gameserver on its own.

You may get a popup from Windows or your firewall asking you if you want to allow connections for this application, select yes.
Not doing this means your firewall may prevent you from connecting.

## Portforwarding

Your server is now open for traffic, but people of course still need to be able to reach your server over the internet.
This is achieved by a process called port forwarding.
This tells your router to listen for certain ports and then forwarding that traffic to your server.

Portforwarding unfortunately looks different for every person depending on what ISP/Router you have, so we can not offer personalized
assistance on how to achieve this for your local setup. Lookup your router/ISP and find a guide online.
There are a lot of Minecraft YouTube videos out there explaining the process, it is the same for this private server.
The technical details needed to porforward are below.

### Router Settings

On your computer that's running the server, open a command prompt and type in this command:

```
ipconfig | findstr /i "IPv4"
```

Copy the private IP it outputs! (`192.168.x.x`, `10.x.x.x` or `172.x.x.x`).

Configure your internet router to port forward following ports: <br>
`TCP/UDP 1757 - 1762` <br>
And forward it to the IP you copied above.

Please note that this is a port RANGE! It means port 1757, 1758, 1759, 1760, 1761 AND 1762, not only 1757 + 1762.
While 1758 and 1760 aren't used, it's easier to just forward that range to keep it tidier on your router.
If you care about having reduced exposure, make three separate rules: <br>
- `UDP 1757` <br>
- `TCP 1761` <br>
- `TCP 1762`

If the server runs TavernVoice, its voice relay uses `UDP 1759` from that range. With separate rules, add one for it.
Without it voice still works, but it goes through the game connection and stutters whenever the server does.

### Firewall Settings

Make sure you have two inbound firewall rules configured for this traffic: <br>
- `TCP 1761 + TCP 1762` <br>
- `UDP 1757` <br>
- `UDP 1759` if you run TavernVoice (or click "Allow" when Windows asks about TavernVoiceRelay.exe) <br>

## Conclusion

All done, your server is now ready and running.
Go ahead and connect to your server by following the "joining" section of this documentation.
