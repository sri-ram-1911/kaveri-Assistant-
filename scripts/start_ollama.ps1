# Start Ollama with model files stored under this workspace (ignored by Git).
# Quit the Ollama tray app first if it already owns the default API port.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$env:OLLAMA_MODELS = Join-Path $repoRoot "ollama_models"
ollama serve
