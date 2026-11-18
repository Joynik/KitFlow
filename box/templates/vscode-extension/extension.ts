import * as vscode from "vscode";

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("my-vscode-extension.hello", () => {
      void vscode.window.showInformationMessage("Hello from your extension!");
    }),
  );
}
