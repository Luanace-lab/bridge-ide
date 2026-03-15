"""
Tests for message_bus.py — Thread-safe Message Store with Typed Events

Tests cover:
  - Message dataclass (creation, to_dict, from_dict)
  - Append (basic, validation, FIFO eviction)
  - Receive (immediate, long-poll, cursor tracking)
  - History (paginated, after_id)
  - Cursor management (get, set, reset)
  - Hooks (register, trigger, unregister)
  - JSONL persistence (save, load)
  - Cleanup (clear, prune)
  - Status reporting
  - Thread safety (concurrent append, receive)
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from message_bus import (
    DEFAULT_MEMORY_CAP,
    MAX_CONTENT_LENGTH,
    MAX_SENDER_LENGTH,
    MESSAGE_TYPES,
    Message,
    MessageBus,
)


class TestMessage(unittest.TestCase):
    """Test Message dataclass."""

    def test_create(self):
        msg = Message(
            id=1, sender="a1", recipient="a2",
            content="hello", timestamp="2026-01-01T00:00:00",
        )
        self.assertEqual(msg.id, 1)
        self.assertEqual(msg.sender, "a1")
        self.assertEqual(msg.message_type, "chat")
        self.assertEqual(msg.meta, {})

    def test_to_dict(self):
        msg = Message(
            id=1, sender="a1", recipient="a2",
            content="hello", timestamp="T",
            message_type="control", meta={"key": "val"},
        )
        d = msg.to_dict()
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["sender"], "a1")
        self.assertEqual(d["message_type"], "control")
        self.assertEqual(d["meta"], {"key": "val"})

    def test_from_dict(self):
        data = {
            "id": 5, "sender": "user", "recipient": "all",
            "content": "hi", "timestamp": "T",
            "message_type": "system", "meta": {},
        }
        msg = Message.from_dict(data)
        self.assertEqual(msg.id, 5)
        self.assertEqual(msg.sender, "user")
        self.assertEqual(msg.message_type, "system")

    def test_from_dict_legacy_keys(self):
        """Test backwards compat with 'from'/'to' keys."""
        data = {"id": 1, "from": "a1", "to": "a2", "content": "x", "timestamp": "T"}
        msg = Message.from_dict(data)
        self.assertEqual(msg.sender, "a1")
        self.assertEqual(msg.recipient, "a2")

    def test_from_dict_defaults(self):
        msg = Message.from_dict({})
        self.assertEqual(msg.id, 0)
        self.assertEqual(msg.sender, "")
        self.assertEqual(msg.message_type, "chat")


class TestMessageTypes(unittest.TestCase):
    """Test message type constants."""

    def test_known_types(self):
        self.assertIn("chat", MESSAGE_TYPES)
        self.assertIn("control", MESSAGE_TYPES)
        self.assertIn("approval_request", MESSAGE_TYPES)
        self.assertIn("system", MESSAGE_TYPES)
        self.assertIn("task_completion", MESSAGE_TYPES)

    def test_immutable(self):
        with self.assertRaises(AttributeError):
            MESSAGE_TYPES.add("new_type")


class TestAppend(unittest.TestCase):
    """Test message append."""

    def setUp(self):
        self.bus = MessageBus()

    def test_basic_append(self):
        msg = self.bus.append("a1", "a2", "hello")
        self.assertEqual(msg.id, 1)
        self.assertEqual(msg.sender, "a1")
        self.assertEqual(msg.recipient, "a2")
        self.assertEqual(msg.content, "hello")
        self.assertEqual(msg.message_type, "chat")

    def test_append_increments_id(self):
        m1 = self.bus.append("a1", "a2", "msg1")
        m2 = self.bus.append("a1", "a2", "msg2")
        self.assertEqual(m1.id, 1)
        self.assertEqual(m2.id, 2)

    def test_append_with_type(self):
        msg = self.bus.append("a1", "a2", "cmd", message_type="control")
        self.assertEqual(msg.message_type, "control")

    def test_append_with_meta(self):
        msg = self.bus.append("a1", "a2", "x", meta={"key": "val"})
        self.assertEqual(msg.meta, {"key": "val"})

    def test_append_sets_timestamp(self):
        msg = self.bus.append("a1", "a2", "x")
        self.assertTrue(len(msg.timestamp) > 0)
        self.assertIn("T", msg.timestamp)

    def test_append_empty_sender_raises(self):
        with self.assertRaises(ValueError):
            self.bus.append("", "a2", "hello")

    def test_append_empty_recipient_raises(self):
        with self.assertRaises(ValueError):
            self.bus.append("a1", "", "hello")

    def test_append_empty_content_raises(self):
        with self.assertRaises(ValueError):
            self.bus.append("a1", "a2", "")

    def test_append_sender_too_long(self):
        with self.assertRaises(ValueError):
            self.bus.append("x" * (MAX_SENDER_LENGTH + 1), "a2", "hello")

    def test_append_content_too_long(self):
        with self.assertRaises(ValueError):
            self.bus.append("a1", "a2", "x" * (MAX_CONTENT_LENGTH + 1))

    def test_fifo_eviction(self):
        bus = MessageBus(memory_cap=5)
        for i in range(10):
            bus.append("a1", "a2", f"msg{i}")
        self.assertEqual(bus.count(), 5)
        # Oldest messages evicted
        msgs = bus.history(limit=10)
        self.assertEqual(msgs[0].content, "msg5")
        self.assertEqual(msgs[-1].content, "msg9")


class TestReceive(unittest.TestCase):
    """Test message receive."""

    def setUp(self):
        self.bus = MessageBus()

    def test_receive_direct(self):
        self.bus.append("a1", "a2", "hello")
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "hello")

    def test_receive_broadcast(self):
        self.bus.append("a1", "all", "broadcast")
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(len(msgs), 1)

    def test_receive_not_for_me(self):
        self.bus.append("a1", "a3", "not for a2")
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(len(msgs), 0)

    def test_receive_cursor_tracking(self):
        self.bus.append("a1", "a2", "msg1")
        self.bus.receive_nowait("a2")  # Advances cursor
        self.bus.append("a1", "a2", "msg2")
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, "msg2")

    def test_receive_limit(self):
        for i in range(10):
            self.bus.append("a1", "a2", f"msg{i}")
        msgs = self.bus.receive_nowait("a2", limit=3)
        self.assertEqual(len(msgs), 3)

    def test_receive_empty(self):
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(msgs, [])

    def test_long_poll_timeout(self):
        start = time.time()
        msgs = self.bus.receive("a2", wait=0.1)
        elapsed = time.time() - start
        self.assertEqual(msgs, [])
        self.assertGreaterEqual(elapsed, 0.05)

    def test_long_poll_wakeup(self):
        result = []

        def receiver():
            msgs = self.bus.receive("a2", wait=5.0)
            result.extend(msgs)

        t = threading.Thread(target=receiver)
        t.start()
        time.sleep(0.05)
        self.bus.append("a1", "a2", "wakeup")
        t.join(timeout=2.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].content, "wakeup")


class TestHistory(unittest.TestCase):
    """Test history queries."""

    def setUp(self):
        self.bus = MessageBus()
        for i in range(20):
            self.bus.append("a1", "a2", f"msg{i}")

    def test_history_default(self):
        msgs = self.bus.history(limit=5)
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[-1].content, "msg19")

    def test_history_all(self):
        msgs = self.bus.history(limit=100)
        self.assertEqual(len(msgs), 20)

    def test_history_after_id(self):
        msgs = self.bus.history(limit=100, after_id=15)
        self.assertEqual(len(msgs), 5)
        self.assertEqual(msgs[0].id, 16)

    def test_history_after_id_none_match(self):
        msgs = self.bus.history(limit=100, after_id=100)
        self.assertEqual(len(msgs), 0)


class TestCursorManagement(unittest.TestCase):
    """Test cursor operations."""

    def setUp(self):
        self.bus = MessageBus()

    def test_get_cursor_default(self):
        self.assertEqual(self.bus.get_cursor("a1"), 0)

    def test_set_cursor(self):
        self.bus.set_cursor("a1", 42)
        self.assertEqual(self.bus.get_cursor("a1"), 42)

    def test_reset_cursor(self):
        self.bus.append("a1", "a2", "msg1")
        self.bus.receive_nowait("a2")
        self.bus.reset_cursor("a2")
        # After reset, should see all messages again
        msgs = self.bus.receive_nowait("a2")
        self.assertEqual(len(msgs), 1)

    def test_cursor_advances(self):
        self.bus.append("a1", "a2", "msg1")
        self.bus.append("a1", "a2", "msg2")
        self.bus.receive_nowait("a2")
        self.assertEqual(self.bus.get_cursor("a2"), 2)


class TestHooks(unittest.TestCase):
    """Test hook registration and triggering."""

    def setUp(self):
        self.bus = MessageBus()
        self.captured = []

    def test_register_and_trigger(self):
        self.bus.register_hook("chat", lambda m: self.captured.append(m))
        self.bus.append("a1", "a2", "hello")
        self.assertEqual(len(self.captured), 1)
        self.assertEqual(self.captured[0].content, "hello")

    def test_hook_only_for_type(self):
        self.bus.register_hook("control", lambda m: self.captured.append(m))
        self.bus.append("a1", "a2", "hello", message_type="chat")
        self.assertEqual(len(self.captured), 0)

    def test_hook_error_ignored(self):
        def bad_hook(m):
            raise RuntimeError("hook error")
        self.bus.register_hook("chat", bad_hook)
        # Should not raise
        msg = self.bus.append("a1", "a2", "hello")
        self.assertIsNotNone(msg)

    def test_unregister_hooks(self):
        self.bus.register_hook("chat", lambda m: self.captured.append(m))
        self.bus.unregister_hooks("chat")
        self.bus.append("a1", "a2", "hello")
        self.assertEqual(len(self.captured), 0)

    def test_multiple_hooks(self):
        self.bus.register_hook("chat", lambda m: self.captured.append("A"))
        self.bus.register_hook("chat", lambda m: self.captured.append("B"))
        self.bus.append("a1", "a2", "hello")
        self.assertEqual(self.captured, ["A", "B"])


class TestBroadcastCallback(unittest.TestCase):
    """Test broadcast callback integration."""

    def test_broadcast_called(self):
        captured = []
        bus = MessageBus(broadcast_fn=lambda m: captured.append(m))
        bus.append("a1", "a2", "hello")
        self.assertEqual(len(captured), 1)

    def test_broadcast_error_ignored(self):
        def bad_broadcast(m):
            raise RuntimeError("broadcast failed")
        bus = MessageBus(broadcast_fn=bad_broadcast)
        msg = bus.append("a1", "a2", "hello")
        self.assertIsNotNone(msg)


class TestPersistence(unittest.TestCase):
    """Test JSONL persistence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.persist_path = Path(self.tmpdir) / "messages.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_persist_on_append(self):
        bus = MessageBus(persist_path=self.persist_path)
        bus.append("a1", "a2", "hello")
        bus.append("a1", "a2", "world")
        self.assertTrue(self.persist_path.exists())
        lines = self.persist_path.read_text().strip().split("\n")
        self.assertEqual(len(lines), 2)

    def test_load_on_init(self):
        # Write some messages
        bus1 = MessageBus(persist_path=self.persist_path)
        bus1.append("a1", "a2", "msg1")
        bus1.append("a1", "a2", "msg2")

        # New bus loads from disk
        bus2 = MessageBus(persist_path=self.persist_path)
        self.assertEqual(bus2.count(), 2)
        msgs = bus2.history(limit=10)
        self.assertEqual(msgs[0].content, "msg1")

    def test_load_continues_id_sequence(self):
        bus1 = MessageBus(persist_path=self.persist_path)
        bus1.append("a1", "a2", "msg1")
        bus1.append("a1", "a2", "msg2")

        bus2 = MessageBus(persist_path=self.persist_path)
        msg3 = bus2.append("a1", "a2", "msg3")
        self.assertEqual(msg3.id, 3)

    def test_no_persist_path(self):
        bus = MessageBus()
        bus.append("a1", "a2", "hello")
        # No crash, no file created
        self.assertEqual(bus.count(), 1)

    def test_persist_creates_dirs(self):
        deep_path = Path(self.tmpdir) / "sub" / "dir" / "messages.jsonl"
        bus = MessageBus(persist_path=deep_path)
        bus.append("a1", "a2", "hello")
        self.assertTrue(deep_path.exists())

    def test_load_corrupt_lines_skipped(self):
        self.persist_path.write_text(
            '{"id":1,"sender":"a1","recipient":"a2","content":"ok","timestamp":"T"}\n'
            'not json\n'
            '{"id":3,"sender":"a1","recipient":"a2","content":"ok2","timestamp":"T"}\n'
        )
        bus = MessageBus(persist_path=self.persist_path)
        self.assertEqual(bus.count(), 2)

    def test_load_applies_memory_cap(self):
        # Write 10 messages
        bus1 = MessageBus(persist_path=self.persist_path)
        for i in range(10):
            bus1.append("a1", "a2", f"msg{i}")

        # Load with cap of 5
        bus2 = MessageBus(persist_path=self.persist_path, memory_cap=5)
        self.assertEqual(bus2.count(), 5)


class TestCleanup(unittest.TestCase):
    """Test cleanup operations."""

    def test_clear(self):
        bus = MessageBus()
        for i in range(10):
            bus.append("a1", "a2", f"msg{i}")
        cleared = bus.clear()
        self.assertEqual(cleared, 10)
        self.assertEqual(bus.count(), 0)

    def test_prune(self):
        bus = MessageBus()
        for i in range(10):
            bus.append("a1", "a2", f"msg{i}")
        pruned = bus.prune(keep=3)
        self.assertEqual(pruned, 7)
        self.assertEqual(bus.count(), 3)

    def test_prune_no_op(self):
        bus = MessageBus()
        for i in range(3):
            bus.append("a1", "a2", f"msg{i}")
        pruned = bus.prune(keep=10)
        self.assertEqual(pruned, 0)


class TestGetMessage(unittest.TestCase):
    """Test single message retrieval."""

    def test_get_by_id(self):
        bus = MessageBus()
        bus.append("a1", "a2", "hello")
        msg = bus.get_message(1)
        self.assertIsNotNone(msg)
        self.assertEqual(msg.content, "hello")

    def test_get_not_found(self):
        bus = MessageBus()
        self.assertIsNone(bus.get_message(999))


class TestCountFor(unittest.TestCase):
    """Test unread count."""

    def test_count_for_agent(self):
        bus = MessageBus()
        bus.append("a1", "a2", "msg1")
        bus.append("a1", "a2", "msg2")
        bus.append("a1", "a3", "not for a2")
        self.assertEqual(bus.count_for("a2"), 2)
        self.assertEqual(bus.count_for("a3"), 1)

    def test_count_after_receive(self):
        bus = MessageBus()
        bus.append("a1", "a2", "msg1")
        bus.receive_nowait("a2")
        self.assertEqual(bus.count_for("a2"), 0)


class TestStatus(unittest.TestCase):
    """Test status reporting."""

    def test_status_empty(self):
        bus = MessageBus()
        s = bus.status()
        self.assertEqual(s["total_messages"], 0)
        self.assertEqual(s["memory_cap"], DEFAULT_MEMORY_CAP)
        self.assertEqual(s["next_id"], 1)
        self.assertEqual(s["active_cursors"], 0)

    def test_status_with_messages(self):
        bus = MessageBus()
        bus.append("a1", "a2", "hello", message_type="chat")
        bus.append("a1", "a2", "cmd", message_type="control")
        bus.receive_nowait("a2")
        s = bus.status()
        self.assertEqual(s["total_messages"], 2)
        self.assertEqual(s["active_cursors"], 1)
        self.assertEqual(s["message_types"]["chat"], 1)
        self.assertEqual(s["message_types"]["control"], 1)


class TestThreadSafety(unittest.TestCase):
    """Test thread safety."""

    def test_concurrent_append(self):
        bus = MessageBus()
        errors = []

        def appender(idx):
            try:
                for j in range(50):
                    bus.append(f"agent_{idx}", "all", f"msg_{idx}_{j}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(bus.count(), 500)

    def test_concurrent_receive(self):
        bus = MessageBus()
        for i in range(100):
            bus.append("sender", "all", f"msg{i}")

        results = {}

        def receiver(agent_id):
            msgs = bus.receive_nowait(agent_id, limit=100)
            results[agent_id] = len(msgs)

        threads = [
            threading.Thread(target=receiver, args=(f"r{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each receiver should get all 100 broadcast messages
        for agent_id, count in results.items():
            self.assertEqual(count, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
