if uv run djlint templates/ --reformat --quiet; then
	:
else
	status=$?
	if [ "$status" -ne 1 ]; then
		exit "$status"
	fi
fi
uv run djlint templates/ --check --quiet --github-output
