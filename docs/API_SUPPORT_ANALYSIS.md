# API-Support Analysis: CLI + API Dual-Backend

Status: Analysis Complete | Priority: Medium (not release-blocking)
Author: Viktor (Systemarchitekt) | Date: 2026-03-17

## Question

Can Bridge ACE offer direct API access in addition to CLI wrappers?

## Current Architecture

All agent interaction goes through tmux:
- `TmuxEngineSpec` (tmux_engine_policy.py) defines per-engine: start_shell, ready_prompt_regex
- Flow: tmux session -> CLI start -> text injection -> output scraping
- 4 engines: claude, codex, qwen, gemini

## API Availability

| Engine | API | SDK | Status |
|--------|-----|-----|--------|
| Claude | Anthropic Messages API | anthropic Python/TS | Production |
| Codex | OpenAI Chat/Completions | openai Python/TS | Production |
| Qwen | Alibaba DashScope API | dashscope Python | Available |
| Gemini | Google AI API | google-generativeai | Production |

## Trade-offs

### Gains with API Backend
- No tmux required (no OAuth, no PATH bugs, no terminal scraping)
- Faster start (~100ms vs ~10s)
- Programmatic control (token counting, streaming, tool-use)
- Docker-friendly (no tmux in container needed)
- No session management overhead

### Losses with API Backend
- No MCP server support (CLIs load MCPs, API does not)
- No resume/context persistence (CLI feature)
- No interactive debugging
- No permission modes (bypassPermissions etc.)
- No built-in file editing tools (Read, Write, Edit, Bash)

## Architecture Proposal

```python
class EngineBackend(Protocol):
    async def start(self, agent_id: str, config: dict) -> bool
    async def send(self, agent_id: str, message: str) -> str
    async def stop(self, agent_id: str) -> bool
    def is_alive(self, agent_id: str) -> bool
    def get_output(self, agent_id: str) -> str

class TmuxBackend(EngineBackend):
    """Existing implementation — wraps CLI tools via tmux."""

class ApiBackend(EngineBackend):
    """New — direct API calls without tmux."""
```

team.json configuration:
```json
{
  "id": "data-worker",
  "engine": "claude",
  "backend": "api",
  "model": "claude-sonnet-4-6"
}
```

## Recommendation

**PARTIAL adoption.** API backend as OPTION, not replacement.

Ideal for:
- Lightweight task workers (no MCP needed)
- Container/cloud deployments
- Fast task execution agents
- Batch processing pipelines

CLI remains default for:
- Full-featured agents with MCP servers
- Resume/context persistence
- Interactive development agents
- Agents needing file system tools

## Implementation Effort

- Phase 1: EngineBackend Protocol + ApiBackend for Claude (2-3 days)
- Phase 2: Add Codex/Qwen/Gemini API backends (1-2 days each)
- Phase 3: team.json backend selection + UI integration (1-2 days)

Total: ~2 weeks for full dual-backend support.

## Decision

Deferred to post-release. Not blocking. Architecture is ready when needed.
