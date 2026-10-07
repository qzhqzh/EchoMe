"""SQLAlchemy models."""

from app.models.knowledge import (  # noqa: F401 -- register knowledge tables in metadata
    KnowledgeAgentToken,
    KnowledgeAsset,
    KnowledgeDecision,
    KnowledgeOverview,
    KnowledgeRecord,
    KnowledgeReference,
    KnowledgeVersion,
)
from app.models.memory import Base, Memory, Project, SyncLog
from app.models.project_knowledge import (
    ArtifactChunk,
    AutomationProposalRun,
    ConstraintEdge,
    ConstraintEvidence,
    ConstraintRevalidationProposal,
    ContextOutcome,
    ContextQualitySnapshot,
    ContextRun,
    EventLink,
    KnowledgeView,
    ProjectAlias,
    ProjectArtifact,
    ProjectConstraint,
    ProjectEvent,
    ProjectRelation,
    ReliabilityAssessment,
)
from app.models.scenario import Scenario, ScenarioItem, ScenarioRun, ScenarioVersion
from app.models.scene_knowledge import SceneKnowledge, SceneKnowledgeChange, SceneKnowledgeEntry
from app.models.user import User

__all__ = [
    "ArtifactChunk",
    "AutomationProposalRun",
    "Base",
    "ConstraintEdge",
    "ConstraintEvidence",
    "ConstraintRevalidationProposal",
    "ContextQualitySnapshot",
    "ContextOutcome",
    "ContextRun",
    "EventLink",
    "KnowledgeView",
    "Memory",
    "Project",
    "ProjectAlias",
    "ProjectArtifact",
    "ProjectConstraint",
    "ProjectEvent",
    "ProjectRelation",
    "ReliabilityAssessment",
    "Scenario",
    "ScenarioItem",
    "ScenarioRun",
    "ScenarioVersion",
    "SceneKnowledge",
    "SceneKnowledgeChange",
    "SceneKnowledgeEntry",
    "SyncLog",
    "User",
]
