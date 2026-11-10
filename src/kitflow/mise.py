"""Replace explicitly owned TOML spans without reformatting user content."""

import re
import tomllib

from kitflow.catalog import Artifact, KitFlowError

MARKER = re.compile(r"^# kitflow:(begin|end) ([A-Za-z0-9_.:-]+)\s*$", re.MULTILINE)
HEADER = re.compile(r"^\s*\[.*\]\s*(?:#.*)?$", re.MULTILINE)


def blocks(text: str) -> dict[str, tuple[int, int, str]]:
    result = {}
    opened = None
    for match in MARKER.finditer(text):
        direction, identity = match.groups()
        if direction == "begin":
            if opened or identity in result:
                raise KitFlowError("Overlapping or duplicate KitFlow markers in mise.toml")
            opened = (identity, match.start(), match.end())
        else:
            if not opened or opened[0] != identity:
                raise KitFlowError(
                    "Unpaired KitFlow markers; remove both markers to detach a block"
                )
            end = match.end()
            if end < len(text) and text[end] == "\n":
                end += 1
            result[identity] = (opened[1], end, text[opened[2] : match.start()].lstrip("\n"))
            opened = None
    if opened:
        raise KitFlowError("Unpaired KitFlow markers; remove both markers to detach a block")
    return result


def parse(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise KitFlowError(f"Invalid mise.toml: {error}") from error


def validate_span(text: str, artifact: Artifact, span: tuple[int, int, str]):
    payload = parse(span[2])
    if artifact.kind == "task":
        if set(payload) != {"tasks"} or set(payload["tasks"]) != {artifact.key}:
            raise KitFlowError(f"Task markers must wrap exactly task {artifact.key}")
    else:
        if set(payload) != {artifact.key}:
            raise KitFlowError(f"Environment markers must wrap exactly {artifact.key}")
        headers = list(HEADER.finditer(text[: span[0]]))
        if not headers or not re.fullmatch(r"\[env\][ \t]*(?:#.*)?", headers[-1].group().strip()):
            raise KitFlowError("Managed environment entries must be inside a plain [env] table")


def replace(text: str, artifact: Artifact, content: bytes | None) -> str:
    owned = blocks(text)
    span = owned.get(artifact.id)
    if span:
        validate_span(text, artifact, span)
    wrapped = ""
    if content is not None:
        wrapped = (
            f"# kitflow:begin {artifact.id}\n{content.decode().rstrip()}\n"
            f"# kitflow:end {artifact.id}\n"
        )
    if span:
        return text[: span[0]] + wrapped + text[span[1] :]
    if content is None:
        return text
    if artifact.kind == "task":
        return text + ("\n" if text else "") + wrapped
    match = re.search(r"^\[env\][ \t]*(?:#.*)?(?:\r?\n|$)", text, re.MULTILINE)
    if match:
        prefix = text[: match.end()]
        if not prefix.endswith("\n"):
            prefix += "\n"
        return prefix + wrapped + text[match.end() :]
    if "env" in parse(text):
        raise KitFlowError("Use a plain [env] table before adding managed environment entries")
    return text + ("\n" if text else "") + "[env]\n" + wrapped


def collision(text: str, artifact: Artifact) -> bool:
    data = parse(text)
    section = "tasks" if artifact.kind == "task" else "env"
    return artifact.key in data.get(section, {})
