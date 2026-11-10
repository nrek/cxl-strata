from __future__ import annotations

import json

from cxl_strata.memory_seal import open_bytes, seal_comment_body, seal_document, seal_memory_event

DEK = bytes(range(32))


def test_import_batch_payload_hides_the_document_body() -> None:
    sealed = seal_document(
        {
            "path": ".md/handoff/cxl-scylla/note.md",
            "kind": "handoff",
            "title": "Visible title",
            "body": "The handoff body must not travel in the clear.",
            "project_slug": "cxl-scylla",
        },
        DEK,
    )
    encoded = json.dumps(sealed)
    assert "The handoff body" not in encoded
    assert "Visible title" not in encoded
    assert sealed["body"] == ""
    assert sealed["content_ciphertext"]
    opened = json.loads(open_bytes(sealed["content_nonce"], sealed["content_ciphertext"], DEK))
    assert opened["body"] == "The handoff body must not travel in the clear."
    assert opened["path"] == ".md/handoff/cxl-scylla/note.md"


def test_comment_and_memory_event_payloads_are_sealed() -> None:
    comment = seal_comment_body("Ship after QA.", DEK)
    assert "Ship after QA." not in json.dumps(comment)
    event = seal_memory_event(
        {
            "project_slug": "cxl-scylla",
            "event_type": "daily_summary",
            "title": "Daily summary",
            "summary": "Closed the memory seal.",
            "local_id": "local-1",
        },
        DEK,
    )
    assert event["local_id"] == "local-1"
    assert "Closed the memory seal." not in json.dumps(event)
    assert event["summary"] == ""
