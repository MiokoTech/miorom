"""
miorom.project - Game Project and Localization Framework.
"""

from miorom.project.assets import Asset, TocArchive, DualTableDialogue, ScriptModule
from miorom.project.protocols import AssetProtocol
from miorom.project.game import Game
from miorom.project.rules import Rule
from miorom.project.scaffold import ProjectScaffold
from miorom.project.manager import (
    ProjectManifest,
    BuildResult,
    ProjectWorkflowManager,
)

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
