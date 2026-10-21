#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Open Port
# @raycast.mode silent
# @raycast.packageName Porthaven

# Optional parameters:
# @raycast.icon ⚓
# @raycast.argument1 { "type": "text", "placeholder": "port or app" }
# @raycast.description Open localhost:<port>, or a saved app's stable address.

PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [[ "$1" =~ ^[0-9]+$ ]]; then
  open "http://localhost:$1/"
else
  url=$(curl -s --noproxy '*' http://127.0.0.1:${PORTHAVEN_PORT:-7475}/api/state | python3 -c "
import json, sys
ref = sys.argv[1].lower()
apps = json.load(sys.stdin)['apps']
a = next((a for a in apps if ref in (a['id'], (a.get('slugName') or '').lower(), a['name'].lower())), None)
print((a or {}).get('stableUrl') or '')" "$1")
  if [ -n "$url" ]; then open "$url"; else echo "No saved app “$1”"; exit 1; fi
fi
