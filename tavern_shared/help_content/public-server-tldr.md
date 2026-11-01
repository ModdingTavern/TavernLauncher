# Setting up a public server for yourself that others can join (TLDR)

## Getting the files for The Modding Tavern

Get the latest version here: <br>
<https://github.com/ModdingTavern/TavernLauncher/releases> <br>

Download: <br>
`TavernLauncher-Server-vX.Y.Z.zip` <br>

Right click it and extract it.

## Running TavernLauncher (Server)

Open the .exe in the extracted folder. <br>
Say "Yes" or "Allow" to any firewall related questions.

## Pointing TavernLauncher to your game

Click the "Browse" button and select: <br>
`C:\Games\Alta\A Township Tale\A Township Tale.exe` <br>

If you installed the game in another directory, point it to the .exe in that folder!

## Patching the game

If you already did this on the client launcher, this section isn't needed again.
If this is the first time: <br>

Click "Patch". <br> 

Second, click "Mods". <br>
Click "Install" on each of the following in order: <br>
- MelonLoader <br>
- TavernLib <br>
- TavernVoice

## Essentials

### Game Port

Leave this on 1757.

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

If you want to give yourself or someone else admin or flycam:

Set any of the following rules for your/their username: <br>
- admin <br>
- mod <br>
- fly

#### Blacklist

Blacklist any usernames/IP's that you don't want joining your server here.

#### Whitelist

Whitelist any username/IP's that you want joining your server here.

#### Whitelist Applications

Any players that applied to your server can be viewed/approved from this window.

## Starting Your Server

Click "Open Server" button to start up your own server. <br>
Say "Yes" or "Allow" to any firewall related questions.

## Portforwarding

Technical details for port forwarding are below. <br>
This guide will not hold your hand through it - it's different for every setup!

### Router Settings

Grab the private IP of the PC running the server in command prompt:

```
ipconfig | findstr /i "IPv4"
```

Copy the private IP (`192.168.x.x`, `10.x.x.x` or `172.x.x.x`).

Configure your internet router port forwarding: <br>
`TCP/UDP 1757 - 1762` <br>
Forward to your copied private IP.

Please note that this is a port RANGE! It means port 1757, 1758, 1759, 1760, 1761 AND 1762, not only 1757 + 1762.
While 1758 and 1760 aren't used, it's easier to just forward that range to keep it tidier on your router.
If you care about having reduced exposure, make three separate rules: <br>
- `UDP 1757` <br>
- `TCP 1761` <br>
- `TCP 1762`

TavernVoice uses `UDP 1759` from that range. With separate rules, add one for it.

### Firewall Settings

Make sure you have two inbound firewall rules configured for this traffic: <br>
- `TCP 1761 + TCP 1762` <br>
- `UDP 1757`

## Conclusion

All done, your server is now ready and running.
Let another player validate they can reach your server over the internet!
