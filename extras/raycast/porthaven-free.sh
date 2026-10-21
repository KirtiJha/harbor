#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Free Port
# @raycast.mode compact
# @raycast.packageName Porthaven

# Optional parameters:
# @raycast.icon ⚓
# @raycast.argument1 { "type": "text", "placeholder": "port" }
# @raycast.description Stop whatever holds a port (the whole app, so it does not respawn).

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
porthaven kill "$1" --app -y | tail -1
