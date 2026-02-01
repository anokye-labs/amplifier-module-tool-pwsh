#!/usr/bin/env python3
"""
Standalone test for the pwsh tool module.
Run with: python test_pwsh_tool.py
"""

import asyncio
import sys
import os

# Mock amplifier_core before importing the module
class MockToolResult:
    def __init__(self, success: bool, output: dict = None, error: dict = None):
        self.success = success
        self.output = output or {}
        self.error = error or {}

    def __repr__(self):
        if self.success:
            return f"ToolResult(success=True, output={self.output})"
        return f"ToolResult(success=False, error={self.error})"


class MockModuleCoordinator:
    async def mount(self, *args, **kwargs):
        pass


class MockAmplifierCore:
    ToolResult = MockToolResult
    ModuleCoordinator = MockModuleCoordinator


# Inject mock before importing
sys.modules["amplifier_core"] = MockAmplifierCore()

# Add module path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amplifier_module_tool_pwsh import PwshTool


async def run_tests():
    print("=" * 60)
    print("Testing tool-pwsh module")
    print("=" * 60)

    tool = PwshTool({"require_approval": False, "timeout": 30})

    # Test 1: Check if PowerShell is found
    print("\n[Test 1] Finding PowerShell")
    pwsh_exe = tool._find_powershell()
    if pwsh_exe:
        print(f"  ✓ Found PowerShell at: {pwsh_exe}")
    else:
        print("  ✗ PowerShell not found - remaining tests will fail")
        return

    # Test 2: Simple command
    print("\n[Test 2] Simple Write-Output command")
    result = await tool.execute({"command": 'Write-Output "Hello from PowerShell!"'})
    print(f"  Success: {result.success}")
    print(f"  Output: {result.output.get('stdout', '').strip()}")
    if not result.success:
        print(f"  Error: {result.error}")

    # Test 3: Environment variable
    print("\n[Test 3] Environment variable access")
    result = await tool.execute({"command": "$env:USERNAME"})
    print(f"  Success: {result.success}")
    print(f"  Username: {result.output.get('stdout', '').strip()}")

    # Test 4: Pipeline command
    print("\n[Test 4] Pipeline command")
    result = await tool.execute(
        {"command": "Get-Process | Select-Object -First 3 Name, Id | Format-Table -AutoSize"}
    )
    print(f"  Success: {result.success}")
    print(f"  Return code: {result.output.get('returncode')}")
    if result.success:
        stdout = result.output.get("stdout", "")
        print(f"  Output preview:\n{stdout[:300]}")

    # Test 5: Math expression
    print("\n[Test 5] PowerShell expression")
    result = await tool.execute({"command": "$a = 10; $b = 20; Write-Output \"Sum: $($a + $b)\""})
    print(f"  Success: {result.success}")
    print(f"  Output: {result.output.get('stdout', '').strip()}")

    # Test 6: Safety check - should be blocked
    print("\n[Test 6] Safety check (should be blocked)")
    result = await tool.execute({"command": "Format-Volume -DriveLetter C"})
    print(f"  Success: {result.success}")
    print(f"  Blocked: {not result.success}")
    if not result.success:
        print(f"  Reason: {result.error.get('message', '')[:80]}")

    # Test 7: Get PowerShell version
    print("\n[Test 7] PowerShell version")
    result = await tool.execute({"command": "$PSVersionTable.PSVersion.ToString()"})
    print(f"  Success: {result.success}")
    print(f"  Version: {result.output.get('stdout', '').strip()}")

    print("\n" + "=" * 60)
    print("Tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
