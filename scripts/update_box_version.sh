#!/usr/bin/env bash
set -euo pipefail

read_version() {
    version=$(cat box/.version)
    [[ "$version" =~ ^[1-9][0-9]{0,17}$ ]]
    base=$(git log -1 --first-parent --format=%H -- box/.version)
    changes=$(git rev-list --first-parent --full-history --count "${base}..HEAD" -- box/ ':(exclude)box/.version')
}

if [[ "${1:-}" == "check" ]]; then
    read_version
    if (( changes != 0 )); then
        echo "Tag a commit that includes the automatic Box version update." >&2
        exit 1
    fi
    exit 0
fi

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in 1 2 3; do
    git fetch origin main
    git switch --detach FETCH_HEAD
    read_version
    if (( changes == 0 )); then
        exit 0
    fi
    printf '%s\n' "$((version + changes))" > box/.version
    git add -- box/.version
    git commit -m "chore(box): update version to $((version + changes))"
    if git push origin HEAD:refs/heads/main; then
        exit 0
    fi
done
exit 1
