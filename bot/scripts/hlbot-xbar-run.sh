#!/bin/bash
CMD="$1"
CTL="$HOME/dev/hl-bot/bot/scripts/hlbot-ctl.sh"
osascript -e "do shell script \"'${CTL}' ${CMD}\"" &>/dev/null &
