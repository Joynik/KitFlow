npm exec --no -- esbuild "$entry" --bundle --platform=node --format=cjs --external:vscode --sourcemap --outfile=dist/extension.js
