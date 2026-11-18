if [ ! -x target/kitflow-tools/bin/cargo-machete ]; then
  printf '%s\n' 'Cargo Machete is missing. Run mise run install-cargo-machete first.' >&2
  exit 1
fi
status=0
output=$(target/kitflow-tools/bin/cargo-machete --quiet --skip-target-dir .) || status=$?
printf '%s\n' "$output" | awk '
  /^If you believe cargo-machete/ { exit }
  NF
'
(exit "$status")
