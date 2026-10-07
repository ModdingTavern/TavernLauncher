# Technical Documentation

## TavernLauncher (Client)

### Game Path

Should always point to "A Township Tale.exe" inside your game directory. <br>
Commonly found in: `C:\Games\Alta\A Township Tale\`

### Username

This is the identity under which you will be known on whichever server you are connecting to. <br>
Good to know: choosing your username on one server does not mean it is automatically the same on another server!
Each servers tracks their own information.

### Platform

Choose what hardware you're playing on. Select Quest for any Meta/Oculus hardware or SteamVR for all others.
"Fly" is a special gamemode that requires certain server privileges in order to work.
See the 'Players - Players' section of the technical documentation of the server TavernLauncher.

### Game Settings

This button will show you all the in-game options and their accepted values to change your gameplay settings. These are the same options
previously controlled via the main menu inside of Township Tale, made external for easier management.

### Destination

This field tracks the IP of the server you are trying to join (public/private), and the port you'll be joining on (should always be 1757 for most cases)

### Saved button

This button shows you the servers you've favorited and joined recently.

### Community Servers

This is the global community server listing. Any server who enabled that option will be broadcast in this menu, making it easier for people to play on servers.
This is hosted by the team of The Modding Tavern themselves and is thus curated. This is an optional service not required for hosting and joining private servers but simply offered as a convenience.

### Tickets

If you have a problem on a private server you're playing on, it's possible to select a server inside this menu and raising a ticket with the admin.
If the admin responds to your ticket this button will flash, alerting you about it.

### Remote Console

If you want to execute commands on your or another server, you can do that via this menu.
In order to do this you'll need access to the console token of that specific server.
You will have to ask the server admin to give this to you.
If you are the server admin, simply look at your server TavernLauncher and click the "Copy Console Token" at the top.

### TavernKeeper

TavernKeeper is a homebrew solution to the old prefabulator. This is basically an admin tool allowing you to do all sorts of manipulatons on your server.
Connect to this functionality with the same TavernLauncher console token as above to get access to it.

## TavernLauncher (Server)

### Game Path

Should always point to "A Township Tale.exe" inside your game directory. <br>
Commonly found in: `C:\Games\Alta\A Township Tale\` <br>

### Game Port

Defaults to 1757, recommended to leave this as is unless you very specifically know what you are doing.

### Server Settings

Contains an array of settings for tweaking your server to your desires.

#### Server Name

The name as you want it to be visible to people.
Some restrictions apply as to how long the name can be.

#### Max Players

Defaults to 24.
Player count can be increased until the maximum of 999 players.

#### Password (optional)

Sets a password on your server, requiring people to enter this before being let in.
Don't forget to click "Set Password" if you fill this in.

#### Enable whitelist (optional)

Enabling this checkbox means you need to fill in the whitelist in the "Player" section of the main application.
Anyone not on the whitelist will automatically be rejected from getting into your server.

#### List on community server browser

This setting means you will publish your server to our API (themoddingtavern.com), making it easy for other players to find your server.
If you do not want your IP known to other players, do not enable this.

#### Limit to 5 accounts per IP

This option is designed to prevent a player from making 100+ entries on your server. Enable this against griefing.

#### Region (optional)

Allows you to submit where your server is hosted. This helps other players determine the best latency when looking at your server in the
server browser.

#### Public Hostname (optional)

If you want your server to be known by a DNS name that you own, you can fill it in here. Make sure that your server is running on the same public IP as to what the DNS resolves to - otherwise the DNS will be rejected on API.

#### Auto-reboot (optional, but recommended)

Leaving a server up for long times can cause performance issues or connectivity issues. Recommended to turn this on to reboot every once in a while to prevent piling of problems.

### Players

Click the "Players" button to open the player management system.
You will see a few different tabs.

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

In this section you can ban specific players from being able to join your server.
At the bottom left you can select if you want to ban a certain username or a certain IP. Simply fill it in to the right of the dropdown
and click "+ Add" to lock in the ban.

#### Whitelist

If you have enabled the whitelist functionality as mentioned above, nobody will be able to join your server unless they match an entry
in your whitelist.
Similar to the blacklist, you can whitelist a username or an IP.
Optionally, you can also write a comment behind each entry so it's easier for you to remember who exactly a certain IP/Username is.

#### Whitelist Applications

If you have enabled the whitelist functionality, players can request to join your server. When they try to connect to your server they will
get a notification that whitelist is enabled. If they are not on that list, they can request access.
Any request will appear in this list and you are able to approve requests or deny them from here. Approving a request means it will automatically
insert their username and IP into the whitelist tab.

### Tickets

Players are able to request help from you through the ticket system. When a user submits a ticket it will become visible in this window.
You can respond or mark tickets as "resolved" to close them.

Good to know: this button will flash if a ticket is pending your feedback.

### Console

Clicking this button will open the command console, allowing you to execute admin commands on your server.

## Additional information

### Game Ports

This section explains what the port range does per port.

| Port | Protocol | Name | Purpose |
|---|---|---|---|
| 1757 | UDP | GamePort | Runs all the communication of your clients to your server and is the backbone of all network syncing. Hard requirement. |
| 1758 | TCP | ServerConsolePort | Legacy port used for server console, repurposed to port 1762. Now obsolete. |
| 1759 | TCP | ServerLoggingPort | Legacy port used for server logging, repurposed to port 1762. Now obsolete. |
| 1760 | TCP | WebsocketPort | Legacy port used for web socket commands, repurposed to port 1762. Now obsolete. |
| 1761 | TCP | WebServerThread | Sends the terrain data cache of the forest to your clients. Without this port clients will not be able to render the terrain of the forest on your server. While not a hard requirement, it kind of is. |
| 1762 | TCP | auth-overlay | A homebrew addon port for The Modding Tavern. This runs the authentication and security protocols for your server. Also a hard requirement. |

### Copy Console Token

Since there is no central authentication (we are not linked to Alta), a homebrew solution was developed to secure admin access.
For people to access your console or TavernKeeper remotely, they need access to your console token.
Do not share this token lightly as it will essentially make someone admin over your server!

### Archive log button

This button will clear the active tracked log in your AppData folder and immediately start a fresh log file.
While the process of logging has been automated and fixed to not go over a certain size, you can still do this manually for troubleshooting
purposes.

### Addons button

TavernLauncher is modular and can be expanded with additional community-made functionality. For this you can enable optional addons from here.
Be very careful enabling any addons that don't come preshipped with the official download in GitHub.

### Wipe Cache button

TavernLauncher tracks certain data on what you've already clicked and read. If you're having severe trouble you can click this to start fresh.

### Enhanced Debugging

Enabling this toggle will provide you with additional debug output inside the MelonLoader console window that opens up together with your game.
You can use this to provide us with additional details if you are having trouble.

### Show MelonLoader

Recommended to leave this on. This opens a small console window together with your server/client which shows debug information for MelonLoader.

### Show Game

Recommended to leave this off. If turned on, the server will launch as a regular application instead of being a hidden process.

### Quest Scene

Enabling this check will load the gameworld as the Quest version. That means the forest is not available and the graphics are generally turned down.

### Tutorial Scene

Enabling this check will load the gameworld as the tutorial scene when the server starts.

### Check Server button

This button can be clicked to probe the status of a server to make sure it's up and to see whether it has a password/whitelist or not.
