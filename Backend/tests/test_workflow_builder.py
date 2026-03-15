import os
import sys
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWorkflowBuilderCompiler(unittest.TestCase):
    def _mod(self):
        try:
            import workflow_builder  # type: ignore
        except ImportError as exc:
            self.fail(f"workflow_builder import failed: {exc}")
        return workflow_builder

    def test_compiles_bridge_actions_and_event_subscription(self):
        mod = self._mod()
        spec = {
            "name": "Bridge Event Pipeline",
            "nodes": [
                {
                    "id": "event_in",
                    "kind": "bridge.trigger.event",
                    "name": "Task Created",
                    "config": {"event_type": "task.created", "filter": {"priority": 1}},
                },
                {
                    "id": "notify_user",
                    "kind": "bridge.action.send_message",
                    "name": "Notify User",
                    "config": {"to": "user", "content": "High priority task created"},
                },
            ],
            "edges": [
                {"from": "event_in", "to": "notify_user"},
            ],
        }

        compiled = mod.compile_bridge_workflow(spec)

        self.assertEqual(compiled["workflow"]["name"], "Bridge Event Pipeline")
        self.assertEqual(len(compiled["workflow"]["nodes"]), 2)
        self.assertEqual(compiled["bridge_subscription"]["event_type"], "task.created")
        self.assertEqual(compiled["bridge_subscription"]["filter"], {"priority": 1})
        self.assertEqual(compiled["workflow"]["nodes"][0]["webhookId"], "bridge-event_in-task-created")
        self.assertEqual(compiled["nodes_by_id"]["notify_user"]["type"], "n8n-nodes-base.httpRequest")
        send_params = compiled["nodes_by_id"]["notify_user"]["parameters"]["bodyParameters"]["parameters"]
        self.assertEqual(send_params[0]["value"], "system")

    def test_defaults_local_bridge_send_message_to_system_sender(self):
        mod = self._mod()
        compiled = mod.compile_bridge_workflow({
            "name": "Local Send",
            "nodes": [
                {
                    "id": "notify",
                    "kind": "bridge.action.send_message",
                    "config": {"to": "user", "content": "hello", "bridge_url": "http://127.0.0.1:9111"},
                }
            ],
            "edges": [],
        })

        send_params = compiled["nodes_by_id"]["notify"]["parameters"]["bodyParameters"]["parameters"]
        self.assertEqual(send_params[0]["name"], "from")
        self.assertEqual(send_params[0]["value"], "system")

    def test_preserves_explicit_sender_and_non_local_default(self):
        mod = self._mod()
        explicit = mod.compile_bridge_workflow({
            "name": "Explicit Sender",
            "nodes": [
                {
                    "id": "notify",
                    "kind": "bridge.action.send_message",
                    "config": {"to": "user", "content": "hello", "from": "workflow-builder"},
                }
            ],
            "edges": [],
        })
        explicit_params = explicit["nodes_by_id"]["notify"]["parameters"]["bodyParameters"]["parameters"]
        self.assertEqual(explicit_params[0]["value"], "workflow-builder")

        remote = mod.compile_bridge_workflow({
            "name": "Remote Sender",
            "nodes": [
                {
                    "id": "notify",
                    "kind": "bridge.action.send_message",
                    "config": {"to": "user", "content": "hello", "bridge_url": "https://bridge.example"},
                }
            ],
            "edges": [],
        })
        remote_params = remote["nodes_by_id"]["notify"]["parameters"]["bodyParameters"]["parameters"]
        self.assertEqual(remote_params[0]["value"], "workflow")

    def test_compiles_raw_n8n_node_and_connections(self):
        mod = self._mod()
        spec = {
            "name": "Raw HTTP Pipeline",
            "nodes": [
                {
                    "id": "sched",
                    "kind": "bridge.trigger.schedule",
                    "config": {"cron": "0 9 * * *"},
                },
                {
                    "id": "fetch",
                    "kind": "n8n.raw",
                    "name": "Fetch API",
                    "node_type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "https://example.com/api", "method": "GET"},
                },
            ],
            "edges": [{"from": "sched", "to": "fetch"}],
        }

        compiled = mod.compile_bridge_workflow(spec)
        workflow = compiled["workflow"]
        source_name = compiled["node_names_by_id"]["sched"]

        self.assertEqual(workflow["nodes"][0]["type"], "n8n-nodes-base.scheduleTrigger")
        self.assertEqual(workflow["nodes"][1]["type"], "n8n-nodes-base.httpRequest")
        self.assertIn(source_name, workflow["connections"])
        first_edge = workflow["connections"][source_name]["main"][0][0]
        self.assertEqual(first_edge["node"], "Fetch API")

    def test_rejects_unknown_edges(self):
        mod = self._mod()
        spec = {
            "name": "Broken Graph",
            "nodes": [
                {"id": "start", "kind": "bridge.trigger.schedule", "config": {"cron": "0 9 * * *"}},
            ],
            "edges": [{"from": "start", "to": "missing"}],
        }

        with self.assertRaises(ValueError):
            mod.compile_bridge_workflow(spec)

    def test_rejects_empty_workflow(self):
        mod = self._mod()
        with self.assertRaises(ValueError):
            mod.compile_bridge_workflow({"name": "Empty", "nodes": [], "edges": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
