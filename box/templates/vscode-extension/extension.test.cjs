const assert = require("node:assert/strict");
const vscode = require("vscode");
const manifest = require("../../package.json");

suite("Extension", () => {
  test("registers its hello command", async () => {
    const extension = vscode.extensions.getExtension(
      `${manifest.publisher}.${manifest.name}`,
    );
    assert.ok(extension);
    await extension.activate();
    const commands = await vscode.commands.getCommands();
    assert.ok(commands.includes("my-vscode-extension.hello"));
  });
});
