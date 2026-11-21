#!/bin/sh
# Schedule refresh-live-data.sh with launchd (macOS): every 3 hours, plus PSA monthly series each Monday at 07:00.
# Usage: ./register-live-data-agent.sh          install / update
#        ./register-live-data-agent.sh remove   uninstall
set -e
APP="$(cd "$(dirname "$0")" && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$APP/logs"

remove() {
  for label in ph.ani.refresh-live ph.ani.refresh-monthly; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
}

write_agent() {  # label, schedule XML, extra argument
  cat > "$AGENTS/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$APP/refresh-live-data.sh</string>${3:+<string>$3</string>}</array>
  <key>WorkingDirectory</key><string>$APP</string>
  $2
  <key>StandardOutPath</key><string>$LOGS/$1.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$1.log</string>
</dict></plist>
PLIST
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$1.plist"
}

remove
[ "$1" = "remove" ] && { echo "Removed the Ani refresh agents."; exit 0; }
mkdir -p "$AGENTS" "$LOGS"
write_agent ph.ani.refresh-live "<key>StartInterval</key><integer>10800</integer><key>RunAtLoad</key><true/>"
write_agent ph.ani.refresh-monthly "<key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>" --monthly
echo "Scheduled: live retail every 3 hours; PSA monthly series Mondays at 07:00. Logs in $LOGS."
