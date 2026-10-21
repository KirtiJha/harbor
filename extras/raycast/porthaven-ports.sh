#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Ports
# @raycast.mode fullOutput
# @raycast.packageName Porthaven

# Optional parameters:
# @raycast.icon ⚓
# @raycast.argument1 { "type": "text", "placeholder": "filter", "optional": true }
# @raycast.description Every listening port: project, framework, HTTP status, uptime.

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -n "$1" ]; then
  porthaven ls | grep -i -- "$1" || echo "Nothing matches “$1”."
else
  porthaven ls
fi
