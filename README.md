<div align="center">
  <img src="ui/assets/organism.png" width="300px" alt="Sovereign Organism Logo">
  
  # SOVEREIGN ENGINE CORE
  
  **Autonomous Agent Runtime & Intelligence GUI**
  
  [![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
  [![Architecture](https://img.shields.io/badge/Architecture-Zero--Trust-red.svg)]()
  [![Status](https://img.shields.io/badge/Build-Production_Grade-success.svg)]()
  [![Engine](https://img.shields.io/badge/Telemetry-CortexDB-8a2be2.svg)]()

  *The conversation window is just an interface. The organism runs underneath.*
</div>

---

## Overview

The **Sovereign Engine Core** is a production-hardened, zero-trust autonomous agent runtime. It establishes a complete multi-LLM operating environment designed to run locally on your hardware. 

Moving beyond generic chat wrappers, the Sovereign Engine functions as a living software organism. It features a decentralized daemon architecture, asynchronous background memory ingestion, deterministic telemetry via the Execution Ledger, and zero-trust payload containment to ensure autonomous agents cannot irreversibly mutate your operating system.

## Core Capabilities

### 🛡️ Zero-Trust Security Interception
Agentic file access is governed by strict containment logic. The payload handlers (`<read>`, `<write>`) are mapped with `is_in_jail(path)` enforcement, hardcap 10MB Out-Of-Memory (OOM) ingestion bypasses, and symlink resolution blocks. **Safety == Trust.**

### 🔮 Omni-Model Routing
Execute seamlessly across top-tier intelligence providers. Natively supports **Gemini**, **Anthropic**, **OpenAI**, and locally-hosted **Ollama** instances. The engine handles protocol normalization, allowing agents to hot-swap logic models dynamically without breaking backend connectivity.

### 🧠 Cortex Memory Fabric
All contexts, code blocks, and decisions are ingested natively into a highly concurrent PostgreSQL schema. Features hot/warm session recovery, execution event journaling, and a completely decoupled asynchronous memory router that protects the UI main thread from database blockages.

### 🎨 Dynamic Aesthetic Generation 
Because the visual runtime matters. The engine ships with a dynamic, real-time CSS variable engine allowing immediate live-swapping of intelligence aesthetics:
- **🟢 Bioforge Green**: The classic terminal moss.
- **🔵 Gemini Forge (Victory)**: High-contrast pure white on deep space indigo with azure particle fog.
- **🟣 Neon Noir**: Hyper-magenta and cyan outrun architecture.
- **❄️ Ghost Protocol**: Clinical arctic blue and silver on deep charcoal.
- **🟠 Cyber Obsidian**: Burnished amber and gold corporate intelligence mapping.

## Architecture

```text
┌─────────────────────────────────────────────────────────┐
│                    ui/index.html                        │
│          (Floating Context UI, No-Terminal UX)          │
└──────────────────────────┬──────────────────────────────┘
                           │ HTTP /api/invoke
                           ▼
┌─────────────────────────────────────────────────────────┐
│                        main.py                          │
│        (FastAPI Server & Inference Router)              │
│   Auto-detects keys, routes to Gemini/Anthropic/Ollama  │
└──────────────────────────┬──────────────────────────────┘
                           │ invokes via AST
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     memory_api.py                       │
│             (Unified Intelligence Client)               │
└────┬────────┬──────────┬───────────┬────────────────────┘
     │ TCP    │ TCP      │ TCP       │ Direct DB / File
     ▼        ▼          ▼           ▼
┌────────┐ ┌────────┐ ┌──────────┐ ┌───────────────────┐
│ Reader │ │ Writer │ │   Loop   │ │     store.py      │
│ :9100  │ │ :9101  │ │ Detector │ │ (Postgres Fabric) │
│        │ │        │ │  :9102   │ │                   │
└────┬───┘ └───┬────┘ └────┬─────┘ └───────┬───────────┘
     │         │           │               │
     ▼         ▼           ▼               ▼
┌─────────────────────────────────────────────────────────┐
│        PostgreSQL Database (Events & Core Memory)       │
│                + synthetic cortex_seed.json             │
└─────────────────────────────────────────────────────────┘
```

## Getting Started

Sovereign is engineered to run flawlessly on bare metal.
Ensure you have Python 3.11+ installed.

### 1. Environment & Database Scaffold
Copy the staging environment credentials and inject your API keys.
```bash
cp .env.example .env
```
*(You can also configure these keys, context limits, and aesthetic themes natively via the visual Configuration Mode in the UI).*

### 2. Ignite the Organism
The engine is packaged for autonomous start. Executing the Guardian script will boot the backend API, the memory daemons, establish the PostgreSQL/SQLite connections, and launch the Electron frontend UI.

```bash
# If running the raw source:
./start.sh 

# If you are compiling via Electron Builder:
cd sov_electron
npm run publish

# If you are compiling via Tauri:
cd src-tauri
cargo build
```

---

> **Axiom 1**: *The Execution Proof Law: the organism cannot claim success without raw execution logs proving it. Confidence without evidence is hallucination.*
