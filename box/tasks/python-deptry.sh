status=0
output=$(uv run --no-sync deptry --no-ansi . 2>&1) || status=$?
printf '%s\n' "$output" | awk '
  /^Scanning [0-9]+ files?\.\.\.$/ { next }
  /^For more information, see the documentation: https:\/\/deptry\.com\/$/ { next }
  NF
'
(exit "$status")
