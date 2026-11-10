"""Seal STRATA payloads with the desktop organization key.

The key is the same DPAPI blob Scylla writes for the signed-in Windows user.
Tests may supply SCYLLA_MEMORY_DEK_HEX instead.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEK_VERSION = 1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def load_dek() -> bytes:
    override = os.environ.get("SCYLLA_MEMORY_DEK_HEX", "").strip()
    if override:
        raw = bytes.fromhex(override)
        if len(raw) != 32:
            raise RuntimeError("SCYLLA_MEMORY_DEK_HEX must be 64 hex characters")
        return raw
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        raise RuntimeError("Team Memory key is unavailable. Open Scylla and sign in before stashing.")
    path = Path(local) / "ScyllaGPT" / "memory-org-dek.bin"
    if not path.is_file():
        raise RuntimeError("Team Memory key is unavailable. Open Scylla and sign in before stashing.")
    return _dpapi_unprotect(path.read_bytes())


def seal_bytes(plain: bytes, dek: bytes | None = None) -> tuple[str, str]:
    key = dek if dek is not None else load_dek()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plain, None)
    return base64.b64encode(nonce).decode(), base64.b64encode(ciphertext).decode()


def open_bytes(nonce_b64: str, ciphertext_b64: str, dek: bytes | None = None) -> bytes:
    key = dek if dek is not None else load_dek()
    nonce = base64.b64decode(nonce_b64)
    ciphertext = base64.b64decode(ciphertext_b64)
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode()


def seal_document(document: dict[str, Any], dek: bytes | None = None) -> dict[str, Any]:
    path = str(document.get("path") or "")
    body = document.get("body") or ""
    title = document.get("title") or ""
    nonce, ciphertext = seal_bytes(
        _canonical({"body": body, "path": path, "title": title, "v": 1}),
        dek,
    )
    sealed = dict(document)
    sealed["body"] = ""
    sealed["title"] = ""
    sealed["path_hash"] = hashlib.sha256(path.encode()).hexdigest()
    sealed["content_nonce"] = nonce
    sealed["content_ciphertext"] = ciphertext
    sealed["dek_version"] = DEK_VERSION
    sealed["content_state"] = "sealed"
    sections = []
    for section in document.get("sections") or []:
        sections.append(seal_section(section, dek))
    if sections:
        sealed["sections"] = sections
    return sealed


def seal_section(section: dict[str, Any], dek: bytes | None = None) -> dict[str, Any]:
    nonce, ciphertext = seal_bytes(
        _canonical({"body": section.get("body") or "", "heading": section.get("heading") or "", "v": 1}),
        dek,
    )
    sealed = dict(section)
    sealed["body"] = ""
    sealed["heading"] = ""
    sealed["content_nonce"] = nonce
    sealed["content_ciphertext"] = ciphertext
    sealed["dek_version"] = DEK_VERSION
    sealed["content_state"] = "sealed"
    return sealed


def seal_comment_body(body: str, dek: bytes | None = None) -> dict[str, str | int]:
    nonce, ciphertext = seal_bytes(_canonical({"body": body, "v": 1}), dek)
    return {
        "body": "",
        "content_nonce": nonce,
        "content_ciphertext": ciphertext,
        "dek_version": DEK_VERSION,
    }


def seal_memory_event(event: dict[str, Any], dek: bytes | None = None) -> dict[str, Any]:
    plain = {
        "details": event.get("details") or "",
        "related_files": event.get("related_files") or [],
        "source_ref": event.get("source_ref") or "",
        "summary": event.get("summary") or "",
        "tags": event.get("tags") or [],
        "title": event.get("title") or "",
        "v": 1,
    }
    nonce, ciphertext = seal_bytes(_canonical(plain), dek)
    sealed = dict(event)
    sealed["title"] = ""
    sealed["summary"] = ""
    sealed["details"] = None
    sealed["source_ref"] = None
    sealed["tags"] = []
    sealed["related_files"] = []
    sealed["content_nonce"] = nonce
    sealed["content_ciphertext"] = ciphertext
    sealed["dek_version"] = DEK_VERSION
    sealed["content_state"] = "sealed"
    return sealed


def reveal_remote_document(row: dict[str, Any], dek: bytes | None = None) -> dict[str, Any]:
    if row.get("content_state") != "sealed":
        return row
    opened = json.loads(open_bytes(row.get("content_nonce") or "", row.get("content_ciphertext") or "", dek))
    revealed = dict(row)
    revealed["path"] = opened.get("path") or row.get("path")
    revealed["title"] = opened.get("title") or ""
    revealed["body"] = opened.get("body") or ""
    comments = []
    for comment in row.get("comments") or []:
        if isinstance(comment, dict) and comment.get("content_state") == "sealed":
            comment_plain = json.loads(
                open_bytes(comment.get("content_nonce") or "", comment.get("content_ciphertext") or "", dek)
            )
            comment = {**comment, "body": comment_plain.get("body") or ""}
        comments.append(comment)
    if comments:
        revealed["comments"] = comments
    return revealed


def _dpapi_unprotect(blob: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(blob)
    incoming = DATA_BLOB(len(blob), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    outgoing = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)
    ):
        raise RuntimeError("Team Memory key could not be unsealed")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)
