[ -n "${I18N_LANGUAGES:-}" ] || { echo "Set vars.i18n_languages" >&2; exit 2; }
for language in $I18N_LANGUAGES; do
    [ "$language" != "${I18N_SOURCE_LANGUAGE:-en}" ] || { echo "Target locales must exclude the source locale" >&2; exit 2; }
done
mkdir -p "$I18N_DIRECTORY"
uv run pybabel extract --mapping-file "$I18N_BABEL_CONFIG" --output-file "$I18N_DIRECTORY/messages.pot" .
for language in $I18N_LANGUAGES; do
    if [ -f "$I18N_DIRECTORY/$language/LC_MESSAGES/messages.po" ]; then
        uv run pybabel update --input-file "$I18N_DIRECTORY/messages.pot" --output-dir "$I18N_DIRECTORY" --locale "$language"
    else
        uv run pybabel init --input-file "$I18N_DIRECTORY/messages.pot" --output-dir "$I18N_DIRECTORY" --locale "$language"
    fi
    uv run pybabel compile --directory "$I18N_DIRECTORY" --locale "$language"
done
