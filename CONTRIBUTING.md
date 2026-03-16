# Contributing to Bridge ACE

## Development Setup

1. Fork and clone the repository
2. Install dependencies: `pip install -r requirements.txt` (if available)
3. Start the server in development mode: `cd Backend && python3 server.py`

## Project Structure

- `Backend/` — Server, MCP, agent management (Python)
- `Frontend/` — Web UI (HTML/CSS/JS)
- `Backend/workflow_templates/` — n8n workflow templates (JSON)

## Guidelines

### Code Style

- Python: Follow existing patterns in server.py (stdlib HTTP, no framework)
- JavaScript: Vanilla JS, no build tools
- CSS: CSS custom properties for theming

### API Changes

- Document new endpoints in the project docs
- Maintain backwards compatibility
- Use consistent error format: `{"error": "description"}`
- Add auth tier where appropriate (see `_path_requires_auth_post`)

### Adding Skills

Skills are managed via Claude Code's built-in skill system (`~/.claude/skills/`).
See the Claude Code documentation for skill creation guidelines.

### Adding Workflow Templates

Create `Backend/workflow_templates/your_template.json`:

```json
{
  "template_id": "tpl_your_template",
  "name": "Template Name",
  "description": "What this workflow does",
  "variables": [],
  "n8n_workflow": { ... },
  "setup_steps": ["Step 1", "Step 2"]
}
```

### Testing

```bash
# Verify server starts
python3 Backend/server.py &
curl http://localhost:9111/health

# Verify syntax
python3 -m py_compile Backend/server.py

# Run tests (if available)
cd Backend && python3 -m pytest tests/
```

## Pull Requests

- Keep changes focused — one feature or fix per PR
- Include before/after for UI changes
- Test with at least one agent running
- Update documentation for API changes

## Security

- Never commit secrets, API keys, or credentials
- Use the credential store for sensitive data
- Validate all user input at API boundaries
- Report security issues privately
