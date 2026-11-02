"""Run unit/API tests with temporary storage and real network connections disabled.

Usage: python -m scripts.test_isolated [--pattern test_inquiry_workflows.py]
MockTransport-based provider tests still run. This is not a live model benchmark.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pattern", default="test_*.py")
    args = parser.parse_args()
    from app import db, docworker, media, zoho

    with (
        tempfile.TemporaryDirectory(prefix="ayyan-tests-") as temporary,
        patch.object(db, "DB_PATH", Path(temporary) / "tests.db"),
        patch.object(media, "ROOT", Path(temporary) / "attachments"),
        patch.object(docworker, "PACKET_DIR", Path(temporary) / "packets"),
        patch.object(zoho, "TOKEN_PATH", Path(temporary) / "no-token.json"),
        patch.object(socket.socket, "connect", side_effect=RuntimeError("Real network disabled in isolated tests")),
    ):
        db.init()
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent.parent / "tests"), pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
