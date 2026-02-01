"""
PowerShell command execution tool for Amplifier.
Includes safety features and approval mechanisms.
"""

# Amplifier module metadata
__amplifier_module_type__ = "tool"

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import sys
from typing import Any

from amplifier_core import ModuleCoordinator, ToolResult

logger = logging.getLogger(__name__)


async def mount(coordinator: ModuleCoordinator, config: dict[str, Any] | None = None):
    """
    Mount the PowerShell tool.

    Args:
        coordinator: Module coordinator
        config: Tool configuration

    Returns:
        Optional cleanup function
    """
    config = config or {}
    tool = PwshTool(config)
    await coordinator.mount("tools", tool, name=tool.name)
    logger.info("Mounted PwshTool")
    return


class PwshTool:
    """Execute PowerShell commands with safety features."""

    name = "pwsh"
    description = """
PowerShell command execution. Use this for Windows-native operations and cross-platform
PowerShell scripts where pwsh is installed.

WHEN TO USE PWSH:
- Windows system administration (Get-Service, Get-Process, registry operations)
- Cross-platform PowerShell scripts
- Working with .NET objects and cmdlets
- Windows-specific package management (winget, chocolatey)
- Azure and Microsoft 365 administration

POWERSHELL FEATURES:
- Object-oriented pipelines: Get-Process | Where-Object CPU -gt 100
- Cmdlets: Get-ChildItem, Invoke-WebRequest, ConvertTo-Json
- Variables: $env:PATH, $HOME, $PSVersionTable
- Cross-platform paths: Join-Path $HOME ".config"

OUTPUT LIMITS:
- Long outputs are automatically truncated to prevent context overflow
- When truncated, you'll see first/last portions with byte counts
- For large output, redirect to file: command | Out-File output.txt

COMMAND GUIDELINES:
- Use cmdlet names for clarity: Get-ChildItem not ls (though aliases work)
- Use splatting for complex commands with many parameters
- Chain commands with |, &&, or ; as needed
- Use `run_in_background` for long-running processes

SAFETY:
- Destructive commands (Remove-Item -Recurse on system paths, Format-Volume) are blocked
- Commands requiring interactive input will fail
                   """

    # Default output limit: ~100KB (roughly 25k tokens)
    DEFAULT_MAX_OUTPUT_BYTES = 100_000

    def __init__(self, config: dict[str, Any]):
        """
        Initialize PowerShell tool.

        Args:
            config: Tool configuration
        """
        self.config = config
        self.require_approval = config.get("require_approval", True)
        self.allowed_commands = config.get("allowed_commands", [])
        self.denied_commands = config.get(
            "denied_commands",
            [
                "Format-Volume",
                "Clear-Disk",
                "Initialize-Disk",
                "Remove-Partition",
                "Stop-Computer",
                "Restart-Computer",
            ],
        )
        self.timeout = config.get("timeout", 30)
        self.working_dir = config.get("working_dir", ".")
        self.max_output_bytes = config.get(
            "max_output_bytes", self.DEFAULT_MAX_OUTPUT_BYTES
        )

    @property
    def input_schema(self) -> dict:
        """Return JSON schema for tool parameters."""
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "PowerShell command to execute",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run command in background, returning immediately with PID. Use for long-running processes.",
                    "default": False,
                },
            },
            "required": ["command"],
        }

    def get_metadata(self) -> dict[str, Any]:
        """Return tool metadata for approval system."""
        return {
            "requires_approval": self.require_approval,
            "approval_hints": {
                "risk_level": "high",
                "dangerous_patterns": self.denied_commands,
                "safe_patterns": self.allowed_commands,
            },
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        """
        Execute a PowerShell command.

        Args:
            input: Dictionary with 'command' and optional 'run_in_background' keys

        Returns:
            Tool result with command output
        """
        command = input.get("command")
        if not command:
            return ToolResult(success=False, error={"message": "Command is required"})

        run_in_background = input.get("run_in_background", False)

        # Safety checks
        is_safe, safety_reason = self._is_safe_command(command)
        if not is_safe:
            return ToolResult(
                success=False,
                error={"message": f"Command denied for safety: {safety_reason}"},
            )

        # Find PowerShell executable
        pwsh_exe = self._find_powershell()
        if not pwsh_exe:
            return ToolResult(
                success=False,
                error={
                    "message": (
                        "PowerShell not found.\n\n"
                        "Install PowerShell Core (recommended):\n"
                        "  https://learn.microsoft.com/en-us/powershell/scripting/install/installing-powershell\n\n"
                        "Windows: winget install Microsoft.PowerShell\n"
                        "macOS: brew install powershell/tap/powershell\n"
                        "Linux: See documentation for your distribution"
                    )
                },
            )

        try:
            if run_in_background:
                result = await self._run_command_background(command, pwsh_exe)
                return ToolResult(
                    success=True,
                    output={
                        "pid": result["pid"],
                        "message": f"Command started in background with PID {result['pid']}",
                        "note": "Use Get-Process or Stop-Process to manage the background process.",
                    },
                )
            else:
                result = await self._run_command(command, pwsh_exe)

                # Apply output truncation
                stdout, stdout_truncated, stdout_bytes = self._truncate_output(
                    result["stdout"]
                )
                stderr, stderr_truncated, stderr_bytes = self._truncate_output(
                    result["stderr"]
                )

                output = {
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result["returncode"],
                }

                if stdout_truncated or stderr_truncated:
                    output["truncated"] = True
                    if stdout_truncated:
                        output["stdout_total_bytes"] = stdout_bytes
                    if stderr_truncated:
                        output["stderr_total_bytes"] = stderr_bytes

                return ToolResult(
                    success=result["returncode"] == 0,
                    output=output,
                )

        except TimeoutError:
            return ToolResult(
                success=False,
                error={"message": f"Command timed out after {self.timeout} seconds"},
            )
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return ToolResult(success=False, error={"message": str(e)})

    def _find_powershell(self) -> str | None:
        """Find PowerShell executable.

        Prefers pwsh (PowerShell Core) over powershell (Windows PowerShell).
        """
        # Try PowerShell Core first (cross-platform)
        pwsh = shutil.which("pwsh")
        if pwsh:
            return pwsh

        # Fall back to Windows PowerShell on Windows
        if sys.platform == "win32":
            powershell = shutil.which("powershell")
            if powershell:
                return powershell

        return None

    def _is_safe_command(self, command: str) -> tuple[bool, str | None]:
        """Check if command is safe to execute.

        Returns:
            Tuple of (is_safe, reason). If is_safe is False, reason explains why.
        """
        command_lower = command.lower()

        # Check against denied commands
        for denied in self.denied_commands:
            if denied.lower() in command_lower:
                return False, f"Matches denied command pattern: {denied}"

        # PowerShell-specific dangerous patterns
        dangerous_patterns = [
            # Disk/partition operations
            ("format-volume", "Disk formatting operation"),
            ("clear-disk", "Disk clearing operation"),
            ("initialize-disk", "Disk initialization"),
            ("remove-partition", "Partition removal"),
            # System operations
            ("stop-computer", "System shutdown"),
            ("restart-computer", "System restart"),
            # Dangerous Remove-Item patterns
            ("remove-item -recurse -force $env:systemroot", "System directory deletion"),
            ("remove-item -recurse -force c:\\windows", "System directory deletion"),
            ("remove-item -recurse -force c:\\", "Root directory deletion"),
            ("remove-item -r -fo c:\\", "Root directory deletion"),
            # Registry dangers
            ("remove-item -path hklm:", "Registry hive deletion"),
            ("remove-itemproperty hklm:", "Registry modification"),
        ]

        for pattern, reason in dangerous_patterns:
            if pattern in command_lower:
                logger.warning(f"Denied dangerous command: {command}")
                return False, reason

        return True, None

    def _truncate_output(self, output: str) -> tuple[str, bool, int]:
        """Truncate output if it exceeds max_output_bytes.

        Returns:
            Tuple of (possibly truncated output, was_truncated, original_bytes)
        """
        original_bytes = len(output.encode("utf-8"))

        if original_bytes <= self.max_output_bytes:
            return output, False, original_bytes

        head_budget = int(self.max_output_bytes * 0.4)
        tail_budget = int(self.max_output_bytes * 0.4)

        lines = output.split("\n")

        # Build head
        head_lines = []
        head_size = 0
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8"))
            if head_size + line_bytes > head_budget:
                break
            head_lines.append(line)
            head_size += line_bytes

        # Build tail
        tail_lines = []
        tail_size = 0
        for line in reversed(lines):
            line_bytes = len((line + "\n").encode("utf-8"))
            if tail_size + line_bytes > tail_budget:
                break
            tail_lines.insert(0, line)
            tail_size += line_bytes

        head_content = "\n".join(head_lines)
        tail_content = "\n".join(tail_lines)

        truncation_indicator = (
            f"\n\n[...OUTPUT TRUNCATED...]\n"
            f"[Showing first {len(head_lines)} lines and last {len(tail_lines)} lines]\n"
            f"[Total output: {original_bytes:,} bytes, limit: {self.max_output_bytes:,} bytes]\n"
            f"[TIP: For large output, use | Out-File output.txt and read the file]\n\n"
        )

        return head_content + truncation_indicator + tail_content, True, original_bytes

    async def _run_command_background(
        self, command: str, pwsh_exe: str
    ) -> dict[str, Any]:
        """Run command in background, returning immediately with PID."""
        is_windows = sys.platform == "win32"
        devnull = subprocess.DEVNULL

        if is_windows:
            process = subprocess.Popen(
                [pwsh_exe, "-NoProfile", "-NonInteractive", "-Command", command],
                stdout=devnull,
                stderr=devnull,
                stdin=devnull,
                cwd=self.working_dir,
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            process = subprocess.Popen(
                [pwsh_exe, "-NoProfile", "-NonInteractive", "-Command", command],
                stdout=devnull,
                stderr=devnull,
                stdin=devnull,
                cwd=self.working_dir,
                start_new_session=True,
            )

        return {"pid": process.pid}

    async def _run_command(self, command: str, pwsh_exe: str) -> dict[str, Any]:
        """Run PowerShell command and wait for completion."""
        is_windows = sys.platform == "win32"

        process = await asyncio.create_subprocess_exec(
            pwsh_exe,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )

            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": process.returncode,
            }

        except TimeoutError:
            # Kill process on timeout
            process.kill()
            try:
                await asyncio.wait_for(process.communicate(), timeout=5)
            except TimeoutError:
                pass
            raise
