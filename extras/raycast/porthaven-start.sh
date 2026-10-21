#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Start App
# @raycast.mode compact
# @raycast.packageName Porthaven

# Optional parameters:
# @raycast.icon ⚓
# @raycast.argument1 { "type": "text", "placeholder": "app" }
# @raycast.description Start a saved app, its dependencies first.

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
porthaven start "$1" | tail -1
