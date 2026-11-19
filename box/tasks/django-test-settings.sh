: "${DJANGO_TEST_SETTINGS_MODULE:?Set DJANGO_TEST_SETTINGS_MODULE to your dedicated test settings module}"
if [ "$DJANGO_TEST_SETTINGS_MODULE" = "${DJANGO_SETTINGS_MODULE:-}" ]; then
    echo "Django tests require a settings module separate from the application." >&2
    exit 2
fi
export DJANGO_SETTINGS_MODULE="$DJANGO_TEST_SETTINGS_MODULE"
