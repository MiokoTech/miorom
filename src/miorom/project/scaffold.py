"""
miorom.project.scaffold
~~~~~~~~~~~~~~~~~~~~~~~
Generates standard project directories and configuration scaffolding for ROM hacking projects.
"""

import os
from typing import Optional


GAME_PY_TEMPLATE = '''"""
{project_name} - MioROM Game Definition
"""

from miorom.project import Game, TocArchive, DualTableDialogue, ScriptModule, Rule


class {class_name}(Game):
    name = "{project_name}"
    platform = "{platform}"
    title = "{project_name} Translation Project"
    default_rom = "original/game.iso"

    # Archives & Containers
    archives = [
        # TocArchive("DATA/files/RUNEFACTORY.bin", "DATA/files/RUNEFACTORY.dat", format="nlcm"),
    ]

    # Dialogues to extract and translate
    dialogues = [
        # DualTableDialogue("extracted/file_1727.fefe", encoding="utf-16-be", id="system_dialog"),
        # ScriptModule("extracted/script.bin", section=2, encoding="utf-16-be", id="story_dialog"),
    ]

    # Localization constraints & tags
    rules = [
        Rule.Textbox(max_chars=34, max_lines=3),
        Rule.TagMap({{
            "<ENTER>": "\\n",
            # "<PLAYER>": "[0x30e9][0x30b0][0x30ca]",
        }}),
    ]


if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    game = {class_name}()
    if action == "analyze":
        game.analyze()
    elif action == "extract":
        game.extract()
    elif action == "validate":
        game.validate()
    elif action == "build":
        game.build()
'''

MIOROM_YAML_TEMPLATE = '''# MioROM Project Configuration
project:
  name: {project_name}
  platform: {platform}
  target_language: Indonesian
  author: MiokoTech
  version: 1.0.0

paths:
  original_rom: original/game.iso
  translations: translations/
  extracted: extracted/
  build: build/
  patches: patches/
'''


class ProjectScaffold:
    """Project template generator."""

    @classmethod
    def generate(cls, project_name: str, dest_dir: Optional[str] = None, platform: str = "wii") -> str:
        target_dir = dest_dir or project_name
        os.makedirs(target_dir, exist_ok=True)

        for subdir in ["original", "extracted", "translations", "build", "patches"]:
            os.makedirs(os.path.join(target_dir, subdir), exist_ok=True)

        class_name = "".join(part.capitalize() for part in project_name.replace("-", "_").split("_"))
        if not class_name:
            class_name = "CustomGame"

        game_py_content = GAME_PY_TEMPLATE.format(
            project_name=project_name,
            class_name=class_name,
            platform=platform,
        )
        with open(os.path.join(target_dir, "game.py"), "w", encoding="utf-8") as f:
            f.write(game_py_content)

        yaml_content = MIOROM_YAML_TEMPLATE.format(
            project_name=project_name,
            platform=platform,
        )
        with open(os.path.join(target_dir, "miorom.yaml"), "w", encoding="utf-8") as f:
            f.write(yaml_content)

        return target_dir
