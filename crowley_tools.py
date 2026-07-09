"""Transport-neutral Crowley tool contract.

This module describes tools without binding them to ChatGPT Actions, MCP, or any
future transport.  Adapters should project these definitions into their public
catalog shape rather than growing transport-specific metadata in the registry.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Literal

ToolKind = Literal["read", "write"]
ToolHandler = Callable[[dict[str, Any]], tuple[dict[str, Any], int | None]]

PermissionTier = Literal[
    "read",
    "validation_write",
    "agent_write",
    "operator_write",
]
WorkflowTier = Literal["core", "secondary"]
McpExposure = Literal[
    "mcp_safe",
    "mcp_conditional",
    "actions_only",
    "local_only",
    "blocked",
]

_VALIDATION_WRITE_TOOLS = frozenset({"writeback.parse"})
_OPERATOR_WRITE_TOOLS = frozenset({"audit.rollback"})
_ACTIONS_ONLY_TOOLS = frozenset({"agent.sync", "agent.deep_sync"})
_LOCAL_ONLY_PREFIXES = (
    "inspect.",
    "github.",
)
_LOCAL_ONLY_TOOLS = frozenset(
    {
        "memory.lifecycle_cleanup",
        "qa.bundle",
    }
)
_BLOCKED_MCP_TOOLS = frozenset({"audit.rollback"})


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    kind: ToolKind
    description: str
    args_schema: dict[str, object]
    handler: ToolHandler
    timeout_seconds: int | None = None
    permission_tier: PermissionTier | None = None
    workflow_tier: WorkflowTier | None = None
    mcp_exposure: McpExposure | None = None
    mcp_notes: str | None = None

    @property
    def input_schema(self) -> dict[str, object]:
        """MCP-facing alias for the existing Actions ``args_schema`` name."""
        return self.args_schema


def coerce_tool_definition(tool: Any) -> ToolDefinition:
    """Convert a registry-like tool object into the shared contract type."""
    if isinstance(tool, ToolDefinition):
        return tool
    return ToolDefinition(
        name=str(tool.name),
        kind=tool.kind,
        description=str(tool.description),
        args_schema=dict(tool.args_schema),
        handler=tool.handler,
        timeout_seconds=getattr(tool, "timeout_seconds", None),
        permission_tier=getattr(tool, "permission_tier", None),
        workflow_tier=getattr(tool, "workflow_tier", None),
        mcp_exposure=getattr(tool, "mcp_exposure", None),
        mcp_notes=getattr(tool, "mcp_notes", None),
    )


def permission_tier_for_tool(name: str, kind: ToolKind) -> PermissionTier:
    if kind == "read":
        return "read"
    if name in _VALIDATION_WRITE_TOOLS:
        return "validation_write"
    if name in _OPERATOR_WRITE_TOOLS:
        return "operator_write"
    return "agent_write"


def mcp_exposure_for_tool(name: str, kind: ToolKind) -> McpExposure:
    if name in _BLOCKED_MCP_TOOLS:
        return "blocked"
    if name in _ACTIONS_ONLY_TOOLS:
        return "actions_only"
    if name in _LOCAL_ONLY_TOOLS or any(
        name.startswith(prefix) for prefix in _LOCAL_ONLY_PREFIXES
    ):
        return "local_only"
    if kind == "read" or name in _VALIDATION_WRITE_TOOLS:
        return "mcp_safe"
    return "mcp_conditional"


def complete_tool_metadata(
    tool: Any,
    *,
    timeout_seconds: int | None = None,
    workflow_tier: WorkflowTier | str | None = None,
) -> ToolDefinition:
    """Return a contract with inferred metadata filled in.

    The inference is intentionally conservative.  It records what an MCP adapter
    would need to decide later without relaxing current Actions gates.
    """
    defn = coerce_tool_definition(tool)
    resolved_workflow = defn.workflow_tier or workflow_tier
    if resolved_workflow is not None and resolved_workflow not in {"core", "secondary"}:
        resolved_workflow = "secondary"
    return replace(
        defn,
        timeout_seconds=defn.timeout_seconds
        if defn.timeout_seconds is not None
        else timeout_seconds,
        permission_tier=defn.permission_tier
        or permission_tier_for_tool(defn.name, defn.kind),
        workflow_tier=resolved_workflow,  # type: ignore[arg-type]
        mcp_exposure=defn.mcp_exposure or mcp_exposure_for_tool(defn.name, defn.kind),
    )


def actions_catalog_entry(
    tool: Any,
    *,
    tier: WorkflowTier | str | None = None,
) -> dict[str, object]:
    """Project a tool contract into the legacy Actions catalog item shape."""
    defn = coerce_tool_definition(tool)
    return {
        "name": defn.name,
        "kind": defn.kind,
        "tier": tier,
        "description": defn.description,
        "args_schema": defn.args_schema,
    }


def contract_metadata(tool: Any) -> dict[str, object]:
    """Return transport-neutral metadata for docs, tests, and future adapters."""
    defn = complete_tool_metadata(tool)
    return {
        "name": defn.name,
        "kind": defn.kind,
        "input_schema": defn.input_schema,
        "timeout_seconds": defn.timeout_seconds,
        "permission_tier": defn.permission_tier,
        "workflow_tier": defn.workflow_tier,
        "mcp_exposure": defn.mcp_exposure,
        "mcp_notes": defn.mcp_notes,
    }
