import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


import server as srv  # noqa: E402


def _template_path(name: str) -> str:
    return os.path.join(ROOT, "workflow_templates", name)


def _load_template(name: str) -> dict:
    with open(_template_path(name), encoding="utf-8") as handle:
        return json.load(handle)


class TestWorkflowTemplateContracts(unittest.TestCase):
    def test_normalize_workflow_template_variables_derives_cron_parts(self):
        normalized = srv._normalize_workflow_template_variables(
            "tpl_daily_status",
            {"cron_time": "09:05", "bridge_url": "http://localhost:9111"},
        )

        self.assertEqual(normalized["cron_hour"], "9")
        self.assertEqual(normalized["cron_minute"], "5")
        self.assertEqual(normalized["bridge_url"], "http://localhost:9111")

    def test_normalize_workflow_template_variables_rejects_invalid_cron_time(self):
        with self.assertRaises(ValueError):
            srv._normalize_workflow_template_variables("tpl_daily_status", {"cron_time": "9"})

    def test_schedule_templates_use_minute_and_hour_placeholders(self):
        for template_name in ("daily_status_report.json", "chat_summary.json"):
            template = _load_template(template_name)
            expression = template["n8n_workflow"]["nodes"][0]["parameters"]["rule"]["interval"][0]["expression"]
            self.assertIn("{{cron_minute}}", expression)
            self.assertIn("{{cron_hour}}", expression)

    def test_schedule_templates_expose_server_timezone_in_metadata(self):
        for template_name in ("daily_status_report.json", "chat_summary.json"):
            template = _load_template(template_name)
            self.assertIn("Server-Zeitzone", template["variables"][0]["label"])
            self.assertIn("Server-Zeitzone", template["setup_steps"][0])

        weekly = _load_template("weekly_report.json")
        self.assertIn("Server-Zeitzone", weekly["setup_steps"][0])

    def test_bridge_url_is_substituted_directly_in_templates(self):
        for template_name in (
            "task_email_notification.json",
            "agent_offline_alert.json",
            "daily_status_report.json",
            "chat_summary.json",
            "weekly_report.json",
        ):
            raw = json.dumps(_load_template(template_name), ensure_ascii=False)
            self.assertIn("{{bridge_url}}", raw)
            self.assertNotIn("$vars.bridge_url", raw)

    def test_daily_status_template_counts_non_disconnected_active_agents(self):
        template = _load_template("daily_status_report.json")
        js_code = template["n8n_workflow"]["nodes"][3]["parameters"]["jsCode"]
        self.assertIn("agent.active !== false", js_code)
        self.assertIn("['offline', 'disconnected']", js_code)

    def test_report_templates_linearize_multi_fetch_before_building_report(self):
        daily = _load_template("daily_status_report.json")["n8n_workflow"]["connections"]
        self.assertEqual(
            daily["Schedule"]["main"],
            [[{"node": "Get Agents", "type": "main", "index": 0}]],
        )
        self.assertEqual(
            daily["Get Agents"]["main"],
            [[{"node": "Get Tasks", "type": "main", "index": 0}]],
        )

        weekly = _load_template("weekly_report.json")["n8n_workflow"]["connections"]
        self.assertEqual(
            weekly["Schedule"]["main"],
            [[{"node": "Get All Tasks", "type": "main", "index": 0}]],
        )
        self.assertEqual(
            weekly["Get All Tasks"]["main"],
            [[{"node": "Get Status", "type": "main", "index": 0}]],
        )

    def test_weekly_report_uses_platform_status_for_online_counts(self):
        template = _load_template("weekly_report.json")
        nodes = template["n8n_workflow"]["nodes"]
        status_node = next(node for node in nodes if node["name"] == "Get Status")
        build_node = next(node for node in nodes if node["name"] == "Build Report")
        self.assertEqual(status_node["parameters"]["url"], "{{bridge_url}}/status")
        js_code = build_node["parameters"]["jsCode"]
        self.assertIn("const platform = status.platform || {}", js_code)
        self.assertIn("platform.online_count", js_code)
        self.assertIn("platform.registered_count", js_code)

    def test_task_notification_template_uses_min_priority_threshold(self):
        template = _load_template("task_email_notification.json")
        filter_node = template["n8n_workflow"]["nodes"][1]
        content_expr = template["n8n_workflow"]["nodes"][2]["parameters"]["bodyParameters"]["parameters"][2]["value"]
        self.assertEqual(filter_node["type"], "n8n-nodes-base.code")
        self.assertEqual(template["n8n_workflow"]["nodes"][0]["parameters"]["path"], "{{webhook_path}}")
        self.assertEqual(template["n8n_workflow"]["nodes"][0]["webhookId"], "{{webhook_path}}")
        self.assertIn("Number(payload.data?.priority || 0)", filter_node["parameters"]["jsCode"])
        self.assertIn("Number('{{min_priority}}')", filter_node["parameters"]["jsCode"])
        self.assertIn("$json.body?.data?.title", content_expr)

    def test_agent_offline_template_uses_code_filter_for_ignore_list(self):
        template = _load_template("agent_offline_alert.json")
        filter_node = template["n8n_workflow"]["nodes"][1]
        self.assertEqual(filter_node["type"], "n8n-nodes-base.code")
        self.assertIn("'{{ignore_agents}}'", filter_node["parameters"]["jsCode"])
        self.assertIn("$input.first().json.body || $input.first().json", filter_node["parameters"]["jsCode"])
        self.assertEqual(template["n8n_workflow"]["nodes"][0]["parameters"]["path"], "{{webhook_path}}")
        self.assertEqual(template["n8n_workflow"]["nodes"][0]["webhookId"], "{{webhook_path}}")

    def test_inject_bridge_workflow_auth_headers_adds_token_only_for_local_bridge_writes(self):
        original = {
            "name": "Auth Probe",
            "nodes": [
                {
                    "name": "Send",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"method": "POST", "url": "http://localhost:9111/send"},
                },
                {
                    "name": "Read",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"method": "GET", "url": "http://localhost:9111/agents"},
                },
                {
                    "name": "External",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"method": "POST", "url": "https://example.com/hook"},
                },
            ],
            "connections": {},
        }

        patched = srv._inject_bridge_workflow_auth_headers(original)

        self.assertNotIn("headerParameters", original["nodes"][0]["parameters"])
        self.assertTrue(patched["nodes"][0]["parameters"]["sendHeaders"])
        headers = patched["nodes"][0]["parameters"]["headerParameters"]["parameters"]
        self.assertEqual(headers[0]["name"], "X-Bridge-Token")
        self.assertEqual(headers[0]["value"], srv.BRIDGE_USER_TOKEN)
        self.assertNotIn("headerParameters", patched["nodes"][1]["parameters"])
        self.assertNotIn("headerParameters", patched["nodes"][2]["parameters"])

    def test_inject_bridge_workflow_auth_headers_normalizes_legacy_bridge_sender_fields(self):
        original = {
            "name": "Legacy Senders",
            "nodes": [
                {
                    "name": "Body Params",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {
                        "method": "POST",
                        "url": "http://localhost:9111/send",
                        "bodyParameters": {
                            "parameters": [
                                {"name": "from", "value": "n8n-digest"},
                                {"name": "to", "value": "user"},
                            ]
                        },
                    },
                },
                {
                    "name": "JSON Body",
                    "type": "n8n-nodes-base.httpRequest",
                    "parameters": {
                        "method": "POST",
                        "url": "http://127.0.0.1:9111/send",
                        "jsonBody": "={{ JSON.stringify({from: 'n8n-events', to: 'user', content: $json.message}) }}",
                    },
                },
            ],
            "connections": {},
        }

        patched = srv._inject_bridge_workflow_auth_headers(original)

        self.assertEqual(
            patched["nodes"][0]["parameters"]["bodyParameters"]["parameters"][0]["value"],
            "system",
        )
        self.assertIn("from: 'system'", patched["nodes"][1]["parameters"]["jsonBody"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
