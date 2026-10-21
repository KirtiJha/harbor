# Porthaven extras

Small companions that talk to a running Porthaven (`porthaven serve`, or `porthaven service install` to start it at
login). None of them needs anything beyond Porthaven itself.

## VS Code, Cursor and Windsurf (`vscode/`)

A status-bar item with the number of ports (it turns amber when something needs you: a dangerously exposed port, a
watched port down, memory that keeps growing, servers left by a coding agent, a config file pointing at a wrong port).
Click it to pick a port and open, copy, stop or show it; the command palette has **Porthaven: Start a saved app**,
**Stop a saved app**, **Free a port** and **Open the dashboard**.

It is plain JavaScript with no build step. Install it from the folder:

```bash
cd extras/vscode
npx @vscode/vsce package --no-dependencies   # makes porthaven-2.1.0.vsix
code --install-extension porthaven-2.1.0.vsix   # or: cursor --install-extension …
```

Settings: `porthaven.url` (default `http://127.0.0.1:7475`) and `porthaven.showSystem`.

## Raycast (`raycast/`)

Script commands: **Ports** (list, with a filter), **Open Port** (a port number or a saved app's name), **Free Port**
and **Start App**. In Raycast: Settings → Extensions → Script Commands → Add Directories, and pick `extras/raycast`.
They call the `porthaven` command, so run `make install` first (it links it into `~/.local/bin`).

## Alfred

`porthaven ls --alfred <query>` prints an Alfred Script Filter. Make a workflow with:

1. **Inputs → Script Filter**: keyword `port`, language `/bin/bash`, script
   `PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH" porthaven ls --alfred "{query}"`.
2. Connect it to **Actions → Open URL** with `{query}`.
3. Optional: a second connection with the ⌘ modifier to **Outputs → Copy to Clipboard**, and one with ⌥ to a
   **Run Script** `porthaven kill {query} --app -y` (Alfred passes the port number for ⌥).

Typing `port 51` lists the matching ports; Enter opens one in the browser.

## Menu bar (`menubar/`)

`porthaven.10s.py` is a plugin for SwiftBar or xbar (macOS) and Argos (GNOME): the ports in the menu bar, with open
and stop actions. Link it into the plugin folder:

```bash
ln -s ~/porthaven/extras/menubar/porthaven.10s.py "$HOME/Library/Application Support/SwiftBar/Plugins/"
```
