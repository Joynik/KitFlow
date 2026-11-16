[ -n "${I18N_LANGUAGES:-}" ] || { echo "Set vars.i18n_languages" >&2; exit 2; }
set --
for language in $I18N_LANGUAGES; do
    [ "$language" != "${I18N_SOURCE_LANGUAGE:-en}" ] || { echo "Target locales must exclude the source locale" >&2; exit 2; }
    set -- "$@" --locale "$language"
done
uv run python manage.py makemessages "$@" --verbosity 0
uv run python manage.py compilemessages "$@" --verbosity 0
