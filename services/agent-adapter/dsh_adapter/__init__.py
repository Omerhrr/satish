"""DeepSeek Harness (DSH) adapter package.

Keeps DSH-specific code behind a controlled adapter (dsh_integration.pattern):
the rest of the application never talks to the model runtime directly.

Phase-0 spike: the upstream surface is pinned via dsh_revision.json
(revision.py) — see docs/dsh-integration.md for the full integration
contract (startup, configuration, tool interface, lifecycle, errors).
"""

from dsh_adapter.client import DeepSeekChatClient, StubChatClient, make_chat_client
from dsh_adapter.revision import (
    LegacyModelError,
    PinnedRevision,
    RevisionError,
    load_revision,
)
from dsh_adapter.runner import NullPersistence, PlanRunner, RunResult
from dsh_adapter.tools import ToolRegistry, ToolSpec, default_registry

__all__ = [
    "DeepSeekChatClient",
    "LegacyModelError",
    "NullPersistence",
    "PinnedRevision",
    "PlanRunner",
    "RevisionError",
    "RunResult",
    "StubChatClient",
    "ToolRegistry",
    "ToolSpec",
    "default_registry",
    "load_revision",
    "make_chat_client",
]
