"""Generate the tap formula from a published release and its checksums."""

import argparse
import json
import re
from pathlib import Path

PLATFORMS = ("macos-arm64", "macos-x86_64", "linux-x86_64")


def formula(release: dict, checksums: str) -> str:
    version = release["tag_name"]
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Expected a stable MAJOR.MINOR.PATCH release")
    if release["draft"] or release["prerelease"]:
        raise ValueError("Expected a published stable release")
    homepage = "https://github.com/Joynik/KitFlow"
    if release["html_url"] != f"{homepage}/releases/tag/{version}":
        raise ValueError("Unexpected release repository")
    hashes = {}
    for line in checksums.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(kitflow-[A-Za-z0-9_.-]+\.tar\.gz)", line)
        if not match or match[2] in hashes:
            raise ValueError("Invalid or duplicate checksum entry")
        hashes[match[2]] = match[1]
    assets = {asset["name"]: asset for asset in release["assets"]}
    rows = {}
    for platform in PLATFORMS:
        name = f"kitflow-{version}-{platform}.tar.gz"
        asset = assets[name]
        url = f"{homepage}/releases/download/{version}/{name}"
        checksum = hashes[name]
        if asset["browser_download_url"] != url or asset["state"] != "uploaded":
            raise ValueError("Missing or unexpected release archive")
        if asset.get("digest") and asset["digest"] != f"sha256:{checksum}":
            raise ValueError("Release asset digest does not match SHA256SUMS")
        rows[platform] = (url, checksum)

    def archive(platform: str, indent: str) -> str:
        url, checksum = rows[platform]
        return f'{indent}url "{url}"\n{indent}sha256 "{checksum}"'

    return f'''# frozen_string_literal: true

class Kitflow < Formula
  desc "Start projects and maintain configuration standards"
  homepage "{homepage}"
  version "{version}"

  on_macos do
    depends_on macos: :sequoia

    if Hardware::CPU.arm?
{archive("macos-arm64", "      ")}
    else
{archive("macos-x86_64", "      ")}
    end
  end

  on_linux do
    depends_on arch: :x86_64

{archive("linux-x86_64", "    ")}
  end

  livecheck do
    url :stable
    strategy :github_latest
  end

  def install
    libexec.install Dir["*"]
    bin.install_symlink libexec/"kitflow"
  end

  test do
    assert_match "KitFlow #{{version}}", shell_output("#{{bin}}/kitflow --version")
  end
end
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--checksums", type=Path, required=True)
    parser.add_argument("--tap", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(args.release.read_text())
    target = args.tap / "Formula/kitflow.rb"
    content = formula(release, args.checksums.read_text())
    if target.exists():
        match = re.search(r'^  version "([0-9.]+)"$', target.read_text(), re.M)
        if not match:
            raise ValueError("Cannot determine the existing formula version")
        current = tuple(map(int, match[1].split(".")))
        incoming = tuple(map(int, release["tag_name"].split(".")))
        if incoming < current:
            raise ValueError("Refusing to downgrade the tap formula")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


if __name__ == "__main__":
    main()
