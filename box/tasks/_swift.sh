case "$usage_action" in build|test|resolve) ;; *) echo "Invalid Swift action" >&2; exit 2 ;; esac
case "$usage_configuration" in Debug) configuration=debug ;; Release) configuration=release ;; *) exit 2 ;; esac
case "${SWIFT_BACKEND:-swiftpm}" in
    swiftpm)
        if [ "$usage_action" = resolve ]; then
            swift package resolve
        else
            # SwiftPM --quiet hides compiler warnings.
            swift "$usage_action" --configuration "$configuration"
        fi
        ;;
    xcode)
        : "${XCODE_PROJECT:?Set vars.xcode_project}"
        : "${XCODE_SCHEME:?Set vars.xcode_scheme}"
        : "${XCODE_DESTINATION:?Set vars.xcode_destination}"
        case "$XCODE_PROJECT" in
            *.xcworkspace) set -- -workspace "$XCODE_PROJECT" ;;
            *.xcodeproj) set -- -project "$XCODE_PROJECT" ;;
            *) echo "Xcode requires a .xcodeproj or .xcworkspace path" >&2; exit 2 ;;
        esac
        action=$usage_action
        if [ "$action" = resolve ]; then action=-resolvePackageDependencies; fi
        xcodebuild -quiet "$@" -scheme "$XCODE_SCHEME" -destination "$XCODE_DESTINATION" -configuration "$usage_configuration" "$action"
        ;;
    *) echo "SWIFT_BACKEND must be swiftpm or xcode" >&2; exit 2 ;;
esac
