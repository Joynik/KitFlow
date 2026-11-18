if [ ! -x node_modules/.bin/knip ]; then
  printf '%s\n' 'Knip is missing. Install the project dependencies first.' >&2
  exit 1
fi
if command -v bun >/dev/null 2>&1; then
  set -- bun node_modules/.bin/knip
else
  set -- node_modules/.bin/knip
fi
"$@" --dependencies --reporter compact --no-progress
