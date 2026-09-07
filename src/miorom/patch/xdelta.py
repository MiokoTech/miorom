import subprocess
import shutil
import os


class XdeltaPatcher:
    """
    Wrapper for xdelta3 tool to create and apply delta patches on ISOs and large ROM images.
    """

    @classmethod
    def is_available(cls) -> bool:
        """Check if xdelta3 executable is in system PATH."""
        return shutil.which("xdelta3") is not None or shutil.which("xdelta") is not None

    @classmethod
    def get_executable(cls) -> str:
        exe = shutil.which("xdelta3") or shutil.which("xdelta")
        if not exe:
            raise FileNotFoundError("xdelta3 executable not found in system PATH. Install it with: apt install xdelta3")
        return exe

    @classmethod
    def create_patch(
        cls,
        source_path: str,
        target_path: str,
        patch_path: str,
        compression_level: int = 9
    ):
        """
        Create an xdelta3 patch between source_path and target_path.
        compression_level: 1 (fastest) to 9 (highest compression).
        """
        exe = cls.get_executable()
        os.makedirs(os.path.dirname(os.path.abspath(patch_path)), exist_ok=True)

        cmd = [
            exe,
            "-e",
            f"-{compression_level}",
            "-f",  # overwrite output if exists
            "-s", source_path,
            target_path,
            patch_path
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"xdelta3 patch creation failed: {res.stderr}")

    @classmethod
    def apply_patch(
        cls,
        source_path: str,
        patch_path: str,
        output_path: str
    ):
        """Apply an xdelta3 patch to source_path to reconstruct output_path."""
        exe = cls.get_executable()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = [
            exe,
            "-d",
            "-f",  # overwrite output if exists
            "-s", source_path,
            patch_path,
            output_path
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"xdelta3 patch application failed: {res.stderr}")
