"""Replace one explicitly marked text block while preserving all surrounding bytes."""

BEGIN = b"# <kitflow>"
END = b"# </kitflow>"
USER = (
    b"\n# <user>\n"
    b"# Rules here are preserved during KitFlow updates.\n"
    b"# Rules in the kitflow block are replaced automatically during updates.\n"
    b"# </user>\n"
)


def span(content: bytes) -> tuple[int, int, bytes] | None:
    markers = []
    offset = 0
    for line in content.splitlines(keepends=True):
        marker = line.rstrip(b"\r\n")
        if marker in {BEGIN, END}:
            markers.append((marker, offset, offset + len(line)))
        offset += len(line)
    if len(markers) != 2 or markers[0][0] != BEGIN or markers[1][0] != END:
        return None
    first, last = markers
    payload = content[first[2] : last[1]]
    if any(line in {b"# <user>", b"# </user>"} for line in payload.splitlines()):
        return None
    return first[1], last[2], payload


def wrap(content: bytes) -> bytes:
    content.decode("utf-8")
    if any(line in {BEGIN, END, b"# <user>", b"# </user>"} for line in content.splitlines()):
        raise ValueError("Block templates must not contain KitFlow or user markers")
    return BEGIN + b"\n" + content + END + b"\n"


def replace(current: bytes | None, content: bytes | None) -> bytes:
    if current is None:
        assert content is not None
        return wrap(content) + USER
    owned = span(current)
    if owned is None:
        raise ValueError("Missing or damaged KitFlow block; leave the file user-owned")
    replacement = wrap(content) if content is not None else b""
    return current[: owned[0]] + replacement + current[owned[1] :]
