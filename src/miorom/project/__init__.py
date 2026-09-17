"""
miorom.project - Game Project and Localization Framework.
"""

from miorom.project.assets import Asset, DualTableDialogue, ScriptModule, TocArchive
from miorom.project.game import Game
from miorom.project.manager import (
    BuildResult,
    ProjectManifest,
    ProjectWorkflowManager,
)
from miorom.project.protocols import AssetProtocol
from miorom.project.rules import Rule
from miorom.project.scaffold import ProjectScaffold

__all__ = [
    "Asset",
    "AssetProtocol",
    "DualTableDialogue",
    "Game",
    "ProjectScaffold",
    "Rule",
    "ScriptModule",
    "TocArchive",
    "ProjectManifest",
    "BuildResult",
    "ProjectWorkflowManager",
]
