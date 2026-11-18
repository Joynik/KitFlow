const vscode = require("vscode");

exports.activate = function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("my-vscode-extension.hello", () => {
      void vscode.window.showInformationMessage("Hello from your extension!");
    }),
  );
};
