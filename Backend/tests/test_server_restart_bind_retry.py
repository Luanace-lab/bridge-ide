from __future__ import annotations

import errno
import os
import sys
import unittest


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import server as srv  # noqa: E402


class TestHttpBindRetry(unittest.TestCase):
    def test_retries_address_in_use_until_server_starts(self) -> None:
        attempts: list[tuple[tuple[str, int], object]] = []
        sleeps: list[float] = []
        sentinel = object()

        def fake_server(bind_addr: tuple[str, int], handler_cls: object) -> object:
            attempts.append((bind_addr, handler_cls))
            if len(attempts) < 3:
                raise OSError(errno.EADDRINUSE, "Address already in use")
            return sentinel

        result = srv._create_http_server_with_retry(
            fake_server,
            ("127.0.0.1", 9111),
            object,
            attempts=5,
            delay_seconds=0.25,
            sleep_fn=sleeps.append,
        )

        self.assertIs(result, sentinel)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [0.25, 0.25])

    def test_non_bind_errors_are_not_retried(self) -> None:
        sleeps: list[float] = []

        def fake_server(_bind_addr: tuple[str, int], _handler_cls: object) -> object:
            raise OSError(errno.EACCES, "Permission denied")

        with self.assertRaises(OSError):
            srv._create_http_server_with_retry(
                fake_server,
                ("127.0.0.1", 9111),
                object,
                attempts=5,
                delay_seconds=0.25,
                sleep_fn=sleeps.append,
            )

        self.assertEqual(sleeps, [])

    def test_exhausts_retry_budget_for_address_in_use(self) -> None:
        attempts = 0
        sleeps: list[float] = []

        def fake_server(_bind_addr: tuple[str, int], _handler_cls: object) -> object:
            nonlocal attempts
            attempts += 1
            raise OSError(errno.EADDRINUSE, "Address already in use")

        with self.assertRaises(OSError):
            srv._create_http_server_with_retry(
                fake_server,
                ("127.0.0.1", 9111),
                object,
                attempts=3,
                delay_seconds=0.25,
                sleep_fn=sleeps.append,
            )

        self.assertEqual(attempts, 3)
        self.assertEqual(sleeps, [0.25, 0.25])


if __name__ == "__main__":
    unittest.main()
