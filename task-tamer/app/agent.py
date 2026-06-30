import os
import re
import json
import logging
import sys
from typing import Any

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, Edge, START, node
from google.adk.tools import AgentTool, McpToolset
from google.adk.tools.mcp_tool import StdioConnectionParams
from mcp import StdioServerParameters
from google.adk.events import RequestInput
from google.adk.agents.context import Context

from app.config import config

# Set up logging for safety audits
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("task_tamer")

# Determine absolute path to mcp_server.py to spawn stdio client
current_dir = os.path.dirname(os.path.abspath(__file__))
mcp_path = os.path.join(current_dir, "mcp_server.py")

# Create local stdio-based MCP toolset
connection_params = StdioConnectionParams(
    server_params=StdioServerParameters(
        command=sys.executable,
        args=[mcp_path],
        env=os.environ.copy()
    )
)
mcp_toolset = McpToolset(connection_params=connection_params)

# Define sub-agents using config.model
task_prioritizer_agent = Agent(
    name="task_prioritizer_agent",
    model=Gemini(model=config.model),
    instruction="""You are the Task Prioritizer Agent. 
Your goal is to list, organize, and prioritize tasks.
You have access to the task database tools.
Analyze input tasks, prioritize them as high, medium, or low, and write them to the database.
Always use get_tasks or add_task tools when appropriate.
Provide clear summaries of the prioritized tasks to the user.""",
    tools=[mcp_toolset]
)

focus_scheduler_agent = Agent(
    name="focus_scheduler_agent",
    model=Gemini(model=config.model),
    instruction="""You are the Focus Scheduler Agent. 
Your goal is to schedule focus blocks and calendar events.
You have access to the calendar database tools.
Schedule focus blocks (specifying title, start time, and duration) and list scheduled calendar events.
Always use schedule_focus_block or get_calendar_events tools when appropriate.""",
    tools=[mcp_toolset]
)

# Wrap sub-agents in AgentTool for delegating orchestrator
prioritizer_tool = AgentTool(agent=task_prioritizer_agent)
scheduler_tool = AgentTool(agent=focus_scheduler_agent)

# Orchestrator agent that delegates actions to sub-agents
orchestrator_agent = Agent(
    name="orchestrator_agent",
    model=Gemini(model=config.model),
    instruction="""You are the TaskTamer Orchestrator. 
Your role is to coordinate user requests for task management and focus scheduling.
- For listing, adding, or prioritizing tasks, delegate to the Task Prioritizer Agent using the prioritizer_tool.
- For scheduling focus blocks, calendar updates, or checking scheduled events, delegate to the Focus Scheduler Agent using the scheduler_tool.
Provide a clear, helpful response explaining what actions were taken by each sub-agent.""",
    tools=[prioritizer_tool, scheduler_tool]
)

# --- Workflow Nodes ---

@node
async def security_checkpoint(ctx: Context, node_input: str) -> str:
    """Validates input against prompt injection, scrubs PII, and runs custom safety rules."""
    # 1. PII Scrubbing (Email & Phone Numbers)
    scrubbed = node_input
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    
    email_matches = re.findall(email_pattern, scrubbed)
    phone_matches = re.findall(phone_pattern, scrubbed)
    
    if email_matches:
        scrubbed = re.sub(email_pattern, "[EMAIL_REDACTED]", scrubbed)
    if phone_matches:
        scrubbed = re.sub(phone_pattern, "[PHONE_REDACTED]", scrubbed)
        
    # 2. Prompt Injection Detection
    injection_keywords = ["ignore previous instructions", "system prompt", "override role", "developer mode"]
    has_injection = any(kw in node_input.lower() for kw in injection_keywords)
    
    # 3. Domain-Specific Rule (Consent / Destructive commands check)
    has_destructive = "delete all" in node_input.lower() or "format database" in node_input.lower()
    
    # 4. Structured JSON Audit Log
    audit_log = {
        "event": "input_security_evaluation",
        "pii_detected": len(email_matches) > 0 or len(phone_matches) > 0,
        "prompt_injection_detected": has_injection,
        "destructive_action_detected": has_destructive,
        "action": "pass"
    }
    
    if has_injection or has_destructive:
        audit_log["action"] = "SECURITY_EVENT"
        logger.warning("SECURITY CRITICAL EVENT: %s", json.dumps(audit_log))
        ctx.route = "SECURITY_EVENT"
        return "SECURITY ALERT: Prompt injection or unauthorized destructive action detected. Access Denied."
        
    logger.info("SECURITY AUDIT: %s", json.dumps(audit_log))
    
    # Store scrubbed query in state for down-stream orchestrator
    ctx.state["scrubbed_input"] = scrubbed
    ctx.route = "pass"
    return scrubbed

@node(rerun_on_resume=True)
async def orchestrator_node(ctx: Context, node_input: str) -> Any:
    """The workflow node executing the orchestrator agent and managing HITL approval."""
    query = ctx.state.get("scrubbed_input", node_input)
    
    # Check if this is a scheduling request to trigger Human-In-The-Loop approval
    is_scheduling = any(w in query.lower() for w in ["schedule", "focus", "block", "calendar"])
    
    if is_scheduling:
        interrupt_id = "confirm_schedule_block"
        approval = ctx.resume_inputs.get(interrupt_id)
        
        # If approval has not been requested/supplied, interrupt the workflow
        if approval is None:
            return RequestInput(
                interrupt_id=interrupt_id,
                message="⚠️ TaskTamer Request: Do you approve scheduling this focus block/event in your calendar? (Reply 'yes' or 'no')",
                response_schema=str
            )
            
        # Resumed path with human feedback
        if "yes" in str(approval).lower():
            logger.info("HITL: User approved focus scheduling request.")
            # Run the agent with context that approval was explicitly granted
            response = await ctx.run_node(orchestrator_agent, f"{query} [USER CONFIRMED AND APPROVED CALENDAR UPDATE]")
            return response
        else:
            logger.info("HITL: User declined focus scheduling request.")
            return "Calendar update cancelled. Focus block was not scheduled."
            
    # Standard query without HITL trigger
    response = await ctx.run_node(orchestrator_agent, query)
    return response

@node
def final_response(ctx: Context, node_input: Any) -> Any:
    """Terminal node that delivers the output from preceding nodes."""
    return node_input

# Build Workflow Graph
task_tamer_workflow = Workflow(
    name="task_tamer_workflow",
    description="Orchestrator workflow for prioritizing tasks and scheduling focus blocks with security checkpoints and HITL.",
    edges=[
        Edge(from_node=START, to_node=security_checkpoint),
        Edge(from_node=security_checkpoint, to_node=orchestrator_node, route="pass"),
        Edge(from_node=security_checkpoint, to_node=final_response, route="SECURITY_EVENT"),
        Edge(from_node=orchestrator_node, to_node=final_response)
    ]
)

# Bind the workflow as the entry point of the app
app = App(
    root_agent=task_tamer_workflow,
    name="app",
)
