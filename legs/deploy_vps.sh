#!/usr/bin/env bash
# Move the paper-leg ticker from the laptop to the VPS. The operator's hand: run once from Git Bash on the laptop.
#
#   bash legs/deploy_vps.sh
#
# Why: the laptop lost power 2026-11-09 03:31Z and was dark for 21 hours (81 bars without a call). A box that
# loses power cannot carry a 100-calls-a-day machine. The VPS already carries the hyperliquid leg.
#
# Order matters so no bar is missed: the ledger goes up while the laptop still ticks, the VPS starts ticking,
# then the laptop's task is disabled. Both write the same call ids for the one overlapping minute; the VPS copy
# is the ledger from then on and `paperleg.py review --pull` reads it (scp, read-only on the VPS).
set -euo pipefail

HOST=root@207.148.31.200
REMOTE=/opt/papertrade/legs
HERE="$(cd "$(dirname "$0")" && pwd)"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=15"

echo "1/5 remote directory, python3, crontab"
PY=$($SSH "$HOST" "mkdir -p $REMOTE/data/board && command -v crontab >/dev/null && command -v python3")
echo "    python3 at $PY"

echo "2/5 code and the ledger as it stands"
scp -q -p "$HERE/paperleg.py" "$HOST:$REMOTE/paperleg.py"
scp -q -p -r "$HERE/data/calls.jsonl" "$HERE/data/tick.log" "$HERE/data/board.jsonl" "$HERE/data/board" "$HOST:$REMOTE/data/"

echo "3/5 cron every minute on the VPS, then one tick now against the grader"
$SSH "$HOST" "( crontab -l 2>/dev/null | grep -v 'papertrade/legs/paperleg.py' ; echo '* * * * * $PY $REMOTE/paperleg.py tick >> $REMOTE/data/cron.err 2>&1' ) | crontab - && $PY $REMOTE/paperleg.py tick && tail -n 2 $REMOTE/data/tick.log"

echo "4/5 the laptop stops writing (task disabled, not deleted)"
powershell.exe -NoProfile -Command "Disable-ScheduledTask -TaskName papertrade-paperleg | Out-Null; (Get-ScheduledTask -TaskName papertrade-paperleg).State"

echo "5/5 the daily review pulls from the VPS"
BOARD="$HOME/.claude/commands/board.md"
if [ -f "$BOARD" ] && ! grep -q 'paperleg.py review <date> --pull' "$BOARD"; then
  sed -i 's#python legs/paperleg.py review <date>#python legs/paperleg.py review <date> --pull#' "$BOARD"
fi
(cd "$HERE/.." && python legs/paperleg.py review --pull)
echo "done. ticker: cron on $HOST. review: python legs/paperleg.py review --pull"
