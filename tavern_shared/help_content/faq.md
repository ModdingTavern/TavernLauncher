# FAQ

## Updating the client

If you are using a TavernLauncher v1.8.3+ edition, you will get update prompts when booting the application.
Simply clicking yes will automatically fetch the latest version and upgrade it.
If this failed somehow, you can still follow this guide to fetch the latest version manually and installing it fresh.

## Running headless servers

Servers can be hosted through two methods:
- Built in via TavernLib
- TavernLauncher

This guide contains the information for TavernLauncher.
If you want to run this on a headless platform (like Docker), there are community resources to do so.
Inform yourself on Discord for this method, or contact "Chaton" as he has built the initial systems for it.

## Being sent to the main menu and not the server

If you end up in the main menu after clicking Join Server, something has gone wrong.
Most often this means one of two things:
- Your game version is the wrong one. Make sure you have the version as marked in the start of this guide, or get a fresh build from the community.
- Your patching process has failed

Sometimes Windows reports "Success" when you click the Patch button - even though it didn't actually succeed.
This is because some machines don't trust the copy/paste operations we're doing automatically.

If your machine did this, it's a good idea to manually do the below:

- Open the "Patch" folder that came with the .zip you downloaded
- Grab the `themoddingtavern.dll` file inside (or grab the most recent version from <https://github.com/ModdingTavern/TavernDefaults/releases>)
- Rename it to `Root.Township.dll`, and copy the file
- Navigate to `C:\Games\Alta\A Township Tale\A Township Tale_Data\Managed` (or wherever you have it installed, same subdirectory)
- Paste the file in this directory and replace the existing one
- Grab the `TavernLib.dll` file from inside the "Patch" folder you downloaded (or grab the most recent version from <https://github.com/ModdingTavern/TavernLib/releases>)
- Navigate to `C:\Games\Alta\A Township Tale\Plugins` (if the folder doesn't exist, make it)
- Paste `TavernLib.dll` here
- Grab the `MelonLoader.x64.zip` archive from the "Patch" folder you downloaded (or get the latest official version at <https://github.com/LavaGang/MelonLoader/releases>)
- Place this .zip file in this directory: `C:\Games\Alta\A Township Tale` and extract it
- You should now have a "MelonLoader" folder inside the same folder as your "A Township Tale.exe" executable
- Grab the `Concentus.dll` file from the "Patch" folder and place it here: `C:\Games\Alta\A Township Tale\UserLibs`
- Grab the `TavernVoice.dll` file from the "Patch" folder and place it here: `C:\Games\Alta\A Township Tale\Mods`
- If `Mods` has any `CircuitsVoiceChat` DLL in it, delete it. TavernVoice replaces it and the two can't run together.

Congratulations, you've now manually done what the "Patch" and "Mods" button tried to do for you!

## Installing MelonLoader/TavernLib/TavernVoice takes x time, is this normal?

If this takes longer than a minute something has probably gone wrong.
Some Windows installations decide to be tough on trying to fetch files from the internet.
If this happens to you, refer to the above section for manually going through the patching/modding process.

## Error texts in the logs

If you see a lot of red text in your logs, do not be afraid. This happens to correct installations as well, the game just reports
a lot of errors by default.
Whenever you see webcalls failing towards `*.alta.com` URL's, they aren't actually doing anything anyway so these are safe to ignore.
If you are in fact experiencing trouble connecting to servers after freshly installing everything, refer to the above questions
regarding manually patching/modding your game. Likely your Windows install didn't fully allow the automatic process.

## Token button is flashing

This button will flash until you've acknowledged it at least once.
This button explains how tokens are used to connect to a private server, and that you are responsible for keeping it safe yourself.
You will notice that you don't have to enter a password for your accounts anywhere - that's a safety measure we implemented.
We didn't want other server hosters knowing what password you might be using in other places as well so instead we work with tokens.
The server validates if a token matches a character when you try to connect.
Losing your token means you no longer have access to that character until an admin restores access for you!
