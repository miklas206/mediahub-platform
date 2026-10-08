"""Validate bounded v1/v2 bencoded metainfo and magnet URI without echoing content."""

import base64
import hashlib
import math
import re
from urllib.parse import parse_qsl, urlsplit


def magnet_hash(value):
    if len(value) > 16384 or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid magnet")
    parsed = urlsplit(value)
    if parsed.scheme != "magnet" or parsed.netloc or parsed.path or parsed.fragment:
        raise ValueError("Invalid magnet")
    values = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=100)
    hashes = []
    for key, item in values:
        if key not in {"xt", "dn", "tr"}:
            raise ValueError("Unsupported magnet field")
        if key == "xt":
            if re.fullmatch(r"urn:btih:[a-fA-F0-9]{40}", item):
                hashes.append(item[9:].lower())
            elif re.fullmatch(r"urn:btih:[a-zA-Z2-7]{32}", item):
                hashes.append(base64.b32decode(item[9:].upper()).hex())
            elif re.fullmatch(r"urn:btmh:1220[a-fA-F0-9]{64}", item):
                hashes.append(item[13:].lower())
            else:
                raise ValueError("Invalid torrent identity")
        if key == "tr" and urlsplit(item).scheme not in {"http", "https", "udp"}:
            raise ValueError("Invalid tracker scheme")
    if not hashes:
        raise ValueError("Missing torrent identity")
    return hashes[0]


def safe_component(value):
    if not isinstance(value, bytes) or not value or len(value) > 255:
        raise ValueError("Invalid torrent path")
    text = value.decode("utf-8", errors="strict")
    if text in {".", ".."} or any(c in text for c in "/\\:\x00") or any(ord(c) < 32 for c in text):
        raise ValueError("Unsafe torrent path")


def torrent_hash(raw):
    if not 1 <= len(raw) <= 2 * 1024 * 1024:
        raise ValueError("Torrent size out of bounds")
    offset = 0
    nodes = 0
    info_bytes = None

    def parse(depth=0):
        nonlocal offset, nodes, info_bytes
        nodes += 1
        if depth > 32 or nodes > 100000 or offset >= len(raw):
            raise ValueError("Invalid metainfo structure")
        token = raw[offset : offset + 1]
        if token == b"i":
            end = raw.index(b"e", offset)
            number = raw[offset + 1 : end]
            if not re.fullmatch(rb"0|[1-9][0-9]{0,18}", number):
                raise ValueError("Invalid metainfo integer")
            offset = end + 1
            return int(number)
        if token in (b"d", b"l"):
            offset += 1
            result = {} if token == b"d" else []
            previous = None
            while offset < len(raw) and raw[offset : offset + 1] != b"e":
                if token == b"l":
                    result.append(parse(depth + 1))
                else:
                    key = parse(depth + 1)
                    if not isinstance(key, bytes) or (previous is not None and key <= previous):
                        raise ValueError("Invalid dictionary order")
                    previous = key
                    start = offset
                    result[key] = parse(depth + 1)
                    if depth == 0 and key == b"info":
                        info_bytes = raw[start:offset]
            if offset >= len(raw):
                raise ValueError("Unterminated metainfo")
            offset += 1
            return result
        end = raw.index(b":", offset)
        length = raw[offset:end]
        if not re.fullmatch(rb"0|[1-9][0-9]{0,7}", length):
            raise ValueError("Invalid metainfo string")
        offset = end + 1
        size = int(length)
        if offset + size > len(raw):
            raise ValueError("Truncated metainfo")
        result = raw[offset : offset + size]
        offset += size
        return result

    doc = parse()
    if offset != len(raw) or not isinstance(doc, dict) or not isinstance(doc.get(b"info"), dict):
        raise ValueError("Invalid metainfo")
    info = doc[b"info"]
    safe_component(info.get(b"name"))
    if b"name.utf-8" in info:
        safe_component(info[b"name.utf-8"])
    if b"symlink path" in info or b"l" in info.get(b"attr", b""):
        raise ValueError("Symlinks not allowed")
    piece_length = info.get(b"piece length")
    if type(piece_length) is not int or not 16384 <= piece_length <= 128 * 1024 * 1024:
        raise ValueError("Invalid piece length")
    if info.get(b"meta version") == 2:

        def tree(node):
            if not isinstance(node, dict):
                raise ValueError("Invalid file tree")
            for key, value in node.items():
                if key == b"":
                    if (
                        not isinstance(value, dict)
                        or type(value.get(b"length")) is not int
                        or b"symlink path" in value
                        or b"l" in value.get(b"attr", b"")
                    ):
                        raise ValueError("Invalid v2 file")
                else:
                    safe_component(key)
                    tree(value)

        tree(info.get(b"file tree"))
    if b"pieces" in info:
        files = info.get(b"files")
        if files is not None:
            if not isinstance(files, list) or not files:
                raise ValueError("Invalid files")
            total = 0
            for file in files:
                if (
                    not isinstance(file, dict)
                    or type(file.get(b"length")) is not int
                    or not file.get(b"path")
                    or b"symlink path" in file
                    or b"l" in file.get(b"attr", b"")
                ):
                    raise ValueError("Invalid file")
                for component in file[b"path"]:
                    safe_component(component)
                if b"path.utf-8" in file:
                    for component in file[b"path.utf-8"]:
                        safe_component(component)
                total += file[b"length"]
        else:
            total = info.get(b"length")
            if type(total) is not int:
                raise ValueError("Missing file length")
        if not isinstance(info[b"pieces"], bytes) or len(info[b"pieces"]) != 20 * math.ceil(
            total / piece_length
        ):
            raise ValueError("Invalid pieces")
        return hashlib.sha1(info_bytes).hexdigest()
    if info.get(b"meta version") != 2:
        raise ValueError("Missing pieces")
    return hashlib.sha256(info_bytes).hexdigest()
