if [ -e .env ] || [ -L .env ]; then
    echo ".env already exists; edit it manually" >&2
    exit 2
fi
(set -C; cat .env.example > .env)
