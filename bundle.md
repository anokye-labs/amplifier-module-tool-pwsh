---
bundle:
  name: tool-pwsh
  version: 1.0.0
  description: >-
    PowerShell tool module with Windows shell guidance.
    Provides the pwsh tool for PowerShell command execution and
    platform-aware context that guides agents to prefer pwsh on Windows.

includes:
  - bundle: tool-pwsh:behaviors/windows-shell
---

# PowerShell Tool for Amplifier

Provides `pwsh` — a PowerShell command execution tool with the same architecture as `tool-bash`:
- Safety system with 4 profiles (strict/standard/permissive/unrestricted)
- Background execution support
- Output truncation with byte-level fallback
- Process group management for clean timeout handling

On Windows, agents will prefer `pwsh` over `bash` based on tool descriptions and injected context.

## Usage

**As a behavior (compose onto existing bundle):**
```
amplifier bundle add git+https://github.com/colombod/amplifier-module-tool-pwsh@main#subdirectory=behaviors/windows-shell.yaml
```

**As a standalone bundle:**
```
amplifier bundle add git+https://github.com/colombod/amplifier-module-tool-pwsh@main
```
