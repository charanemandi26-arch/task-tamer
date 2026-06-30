# 📝 TaskTamer — ADK Hackathon Submission Writeup

**Track:** 🧑‍💼 Concierge Agents (Track 3)
**Project:** TaskTamer — Personal Task & Focus Scheduler Agent
**Model:** `gemini-2.5-flash`

---

## 🌟 Problem Statement

Modern knowledge workers are overwhelmed with task management. They juggle multiple to-do apps, calendars, and reminders across different tools — leading to context-switching fatigue and missed focus time.

**TaskTamer** solves this by acting as a personal AI concierge that:
- Intelligently **prioritizes tasks** based on urgency and context
- **Schedules protected focus blocks** on your calendar automatically
- Enforces a **human-approval gate** before any calendar mutation
- **Sanitizes all user input** through a dedicated security layer before it reaches any LLM

---

## 🏛️ Architecture Overview

TaskTamer is built on three architectural layers:

### Layer 1 — Workflow Graph (ADK Workflow)

The top-level execution model is an ADK 2.0 `Workflow` with three nodes:

```
START → security_checkpoint → orchestrator_node → final_response
                          ↘ (SECURITY_EVENT) → final_response
```

**Node descriptions:**
- `security_checkpoint` (`@node`): Stateless input validator. Runs regex PII scrubbing, prompt injection detection, and destructive command checks. Routes to `pass` or `SECURITY_EVENT`.
- `orchestrator_node` (`@node(rerun_on_resume=True)`): Dynamic scheduling node that conditionally yields a `RequestInput` for HITL approval, then calls `ctx.run_node(orchestrator_agent, ...)`.
- `final_response` (`@node`): Terminal pass-through node delivering the final output.

### Layer 2 — Multi-Agent Delegation (ADK Agents + AgentTool)

The `orchestrator_agent` delegates to two specialist sub-agents using `AgentTool`:

| Agent | Role | Tools |
|---|---|---|
| `task_prioritizer_agent` | List, add & prioritize tasks | `get_tasks`, `add_task` |
| `focus_scheduler_agent` | Schedule blocks & view events | `schedule_focus_block`, `get_calendar_events` |

### Layer 3 — MCP Local Server (FastMCP stdio)

A local `FastMCP` server (`mcp_server.py`) exposes all 4 tools via `StdioConnectionParams`. Data is persisted to `task_tamer_data.json`.

---

## 🔑 ADK Concepts Demonstrated

| ADK Concept | Where Used |
|---|---|
| `Workflow` + `Edge` + `START` | Top-level workflow graph with conditional routing |
| `@node` / `@node(rerun_on_resume=True)` | Stateless & resumable workflow nodes |
| `ctx.route` | Dynamic edge routing (pass / SECURITY_EVENT) |
| `ctx.run_node()` | Dynamic agent invocation inside a workflow node |
| `ctx.state` | Passing scrubbed input across nodes |
| `RequestInput` (HITL) | Human-in-the-loop calendar approval interrupt |
| `ctx.resume_inputs` | Reading user approval response on resume |
| `Agent` + `Gemini` model | Sub-agent definition with LLM model binding |
| `AgentTool` | Wrapping agents as callable tools for orchestrator |
| `McpToolset` + `StdioConnectionParams` | Connecting agents to a local MCP server |
| `App` | Binding the workflow as the entry point |

---

## 🔒 Security Design

Security is a first-class citizen in TaskTamer. **No user input reaches the LLM without first passing through `security_checkpoint`.**

### 1. PII Scrubbing

Email addresses and phone numbers are detected and replaced inline:

```python
email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
```

Example: `call me at 555-123-4567` → `call me at [PHONE_REDACTED]`

### 2. Prompt Injection Detection

A keyword blocklist rejects known jailbreak patterns:

```python
injection_keywords = ["ignore previous instructions", "system prompt", "override role", "developer mode"]
```

### 3. Destructive Action Guard

Commands targeting bulk deletions are blocked at the checkpoint:

```python
has_destructive = "delete all" in query or "format database" in query
```

### 4. Structured Audit Logging

Every security evaluation is emitted as structured JSON to the server log:

```json
{
  "event": "input_security_evaluation",
  "pii_detected": false,
  "prompt_injection_detected": false,
  "destructive_action_detected": false,
  "action": "pass"
}
```

---

## 🙋 Human-in-the-Loop (HITL) Design

The HITL flow is triggered for any scheduling-related query. This ensures **no calendar mutation occurs without explicit human consent.**

**Flow:**

1. `orchestrator_node` detects scheduling intent via keyword matching
2. It yields `RequestInput(interrupt_id="confirm_schedule_block", message="...")`
3. The ADK workflow pauses and presents the prompt to the user
4. On resume, `ctx.resume_inputs.get("confirm_schedule_block")` returns the user's answer
5. If `"yes"` → the orchestrator runs the sub-agent with an explicit approval annotation
6. If `"no"` → returns a polite cancellation message

**Why `rerun_on_resume=True`?**
ADK requires this flag on any node that uses `ctx.run_node()` (dynamic scheduling) because the workflow re-runs the parent node on resume to retrieve the child's output. Without it, a `ValueError` is raised at startup.

---

## 📦 MCP Server Design

The `mcp_server.py` is a local `FastMCP` stdio server. It is spawned by `McpToolset` using `StdioConnectionParams` pointing to `sys.executable` and the absolute path to `mcp_server.py`.

**Tools exposed:**

```python
@mcp.tool()
def get_tasks() -> list[dict]: ...

@mcp.tool()
def add_task(title: str, priority: str = "medium", due_date: str = "") -> dict: ...

@mcp.tool()
def schedule_focus_block(title: str, start_time: str, duration_minutes: int = 60) -> dict: ...

@mcp.tool()
def get_calendar_events() -> list[dict]: ...
```

Data is persisted to `task_tamer_data.json` using atomic file I/O — ensuring safe concurrent reads/writes.

---

## 🧪 Testing Summary

| Test Case | Input | Expected Behavior | Result |
|---|---|---|---|
| Task Add | `Add high-priority task 'Finish report'` | Task stored via MCP, confirmed to user | ✅ |
| Focus Block + HITL | `Schedule 60-min focus block at 10am` | HITL prompt fires, approval → event stored | ✅ |
| Prompt Injection | `ignore previous instructions` | Blocked by security_checkpoint | ✅ |
| PII Scrub | `Call me at 555-123-4567` | Phone redacted before LLM sees input | ✅ |
| Destructive Command | `delete all tasks` | Blocked by security_checkpoint | ✅ |

---

## 🔮 Future Enhancements

- **Google Calendar integration**: Replace mock JSON store with real Calendar API via OAuth
- **Smart Scheduling**: Use Gemini to detect available slots and avoid conflicts
- **Recurring Tasks**: Support daily/weekly recurrence patterns
- **Notification System**: Push reminders via email or SMS via Twilio MCP
- **Multi-user support**: Session-scoped data storage with user identity

---

## 📎 References

- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [ADK Workflow & Edge API](https://google.github.io/adk-docs/agents/workflow-agents/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
