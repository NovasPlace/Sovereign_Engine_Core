import os
import sys
import json
import time
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# We rely on memory_api.py for logging events
sys.path.append(str(Path(__file__).parent.parent))
from memory_api import MemoryAPI

# Evolution Forge Configuration
class ForgeContext:
    def __init__(self):
        self.provider = os.getenv("FORGE_PROVIDER", "nim").strip().lower()
        if self.provider == "nim":
            self.synth_model = "deepseek-ai/deepseek-v3.1"
            self.eval_model = "meta/llama-3.1-405b-instruct"
            self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        else:
            self.synth_model = "deepseek-coder-v2:lite"
            self.eval_model = "llama3.1:8b-instruct-q4_K_M"
            self.base_url = os.getenv("SOVEREIGN_OLLAMA_URL", "http://localhost:11434").strip().rstrip("/") + "/api/chat"
            self.ollama_api_key = os.getenv("SOVEREIGN_OLLAMA_API_KEY", "").strip()
            
        keys_str = os.getenv("SOVEREIGN_NIM_API_KEYS", "")
        self.keypool = [k.strip() for k in keys_str.split(",") if k.strip()]
        self.key_idx = 0

    def get_nim_key(self) -> str:
        k = self.keypool[self.key_idx]
        self.key_idx = (self.key_idx + 1) % len(self.keypool)
        return k

class EvolutionForge:
    """
    Blast Chamber Execution & Dynamic Tool Forge

    This organ takes natural language tasks, writes Python tools using 
    NVIDIA's frontier models, tests them in isolated ephemeral Docker containers,
    and if successful, dynamically drops them into the `tools/` directory.
    """

    def __init__(self):
        self.api = MemoryAPI()
        self.ctx = ForgeContext()
        
        if self.ctx.provider == "nim" and not self.ctx.keypool:
            raise ValueError("[Forge] FORGE_PROVIDER=nim but no SOVEREIGN_NIM_API_KEYS found.")
            
        self.tools_dir = Path(__file__).parent.parent / "tools"
        self.tools_dir.mkdir(exist_ok=True, parents=True)

    def synthesize_tool(self, task_description: str, max_retries: int = 3) -> bool:
        """
        The core Controller Loop for tool evolution.
        Requests tool schema + impl, runs test, commits on pass.
        Returns True if successful.
        """
        # CortexDB: Pull past failures to prevent repetition
        try:
            hot_memory = self.api.get_hot()
            lessons_block = ""
            if "LESSONS" in hot_memory.upper():
                lessons_block = "\n--- RECENT CORTEXDB LESSONS (DO NOT REPEAT THESE ERRORS) ---\n" + hot_memory[-2000:] + "\n--------------------------------------------------------------\n"
        except:
            lessons_block = ""

        prompt_context = f"""
You are the Tool Forge for the Sovereign Engine.
We need a self-contained Python script to solve this task: {task_description}
{lessons_block}
Provide a JSON object containing EXACTLY:
{{
  "filename": "snake_case_name.py",
  "schema": "A brief docstring sentence describing what the tool does.",
  "code": "The raw Python 3 source code snippet for the tool."
}}
        
Requirements for `code`:
1. Include a single entrypoint function.
2. Under if __name__ == '__main__':, include a mock test that executes the function perfectly and asserts correct logic. If the test fails, print a descriptive error message to stdout before calling `exit(1)`. On success, print 'pass' and exit(0).
3. No network code unless specifically asked. Only standard library.
"""
        history = [{"role": "system", "content": "You are a senior systems engineer acting as the Sovereign Tool Forge. Return ONLY valid JSON, no markdown blocks."}]
        history.append({"role": "user", "content": prompt_context})
        
        for attempt in range(1, max_retries + 1):
            active_model = self.ctx.synth_model if attempt == 1 else self.ctx.eval_model
            print(f"[Forge] Attempt {attempt}/{max_retries} | Provider: {self.ctx.provider} | Model: {active_model} | Task: {task_description[:30]}...")
            
            try:
                response = self._call_api(history, active_model)
                response = response.strip()
                if response.startswith("```json"):
                    response = response[7:]
                if response.startswith("```"):
                    response = response[3:]
                if response.endswith("```"):
                    response = response[:-3]

                tool_data = json.loads(response.strip())
                filename = tool_data["filename"]
                code_str = tool_data["code"]
                schema_str = tool_data["schema"]
                
                # Execute Blast Chamber Test
                passed, error_output = self._run_blast_chamber(code_str)
                
                if passed:
                    self._equip_tool(filename, code_str, schema_str)
                    print(f"[Forge] SUCCESS: Dynamically equipped {filename}")
                    self.api.emit_event("decision", f"Successfully evolved and equipped tool: {filename}", project="Sovereign Engine Core")
                    return True
                else:
                    print(f"[Forge] Blast Chamber REJECTED build. Error: \n{error_output}")
                    history.append({"role": "assistant", "content": json.dumps(tool_data)})
                    history.append({"role": "user", "content": f"The test failed inside the isolated execution container. Here is the stderr output. Fix the logic and output the full correct JSON again:\n\n{error_output}"})
            
            except Exception as e:
                print(f"[Forge] Synthesis exception: {e}")
                history.append({"role": "user", "content": f"Failed to parse JSON or internal error: {e}. Provide ONLY valid unescaped JSON."})
                time.sleep(2)

        # Total failure path - Commit lesson to CortexDB
        print("[Forge] ABORT. Mutation failed correctness gauntlet completely.")
        failure_lesson = f"Evolution Forge failed to synthesize tool for '{task_description}'. Last error: {error_output[-500:]}"
        self.api.lesson(failure_lesson)
        self.api.emit_event("lesson", failure_lesson, project="Sovereign Engine Core")
        return False

    def _call_api(self, messages: list, model: str) -> str:
        """Dual-provider router for API calls with mandatory Iron Anchor constraint layer."""
        # ALL Synthesis logic routing now passes through the PyTorch Immune Subprocess natively
        # Evaluator logic (which uses evaluate models) will bypass PyTorch to save cycles
        if self.ctx.provider == "nim" and "synth" not in str(model).lower():
            payload = json.dumps({"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 2000}).encode("utf-8")
            req = urllib.request.Request(self.ctx.base_url, data=payload, headers={"Authorization": f"Bearer {self.ctx.get_nim_key()}", "Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())["choices"][0]["message"]["content"]
        else:
            # === IRON ANCHOR: CONFIDENCE CALIBRATION INTERCEPT ===
            print("[Evolution Forge] Synthesizing tool through the Confidence Calibration Anchor (PyTorch)...")
            anchored_path = os.path.join(os.path.dirname(__file__), "dynamic_anchored_inference.py")
            cmd = [sys.executable, anchored_path, "--messages", json.dumps(messages)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            return res.stdout.strip() if res.stdout.strip() else f'{{"filename": "error.py", "schema": "Process failed", "code": "print(\'{res.stderr.strip()}\')"}}'

    def _run_blast_chamber(self, code: str) -> tuple[bool, str]:
        """
        Creates an ephemeral sandbox, writes the code, spins up a Docker container 
        with no network, and tests the code. Clears the sandbox.
        """
        with tempfile.TemporaryDirectory(prefix="forge_sandbox_") as tmpdir:
            test_file = Path(tmpdir) / "tool_test.py"
            test_file.write_text(code, encoding="utf-8")
            
            os.chmod(tmpdir, 0o777)
            os.chmod(test_file, 0o777)
            
            # Subprocess -> Docker
            # Read-only mount, network disabled, drop capabilities
            cmd = [
                "docker", "run", "--rm", 
                "--network", "none",
                "--security-opt", "no-new-privileges:true",
                "--cap-drop", "ALL",
                "-v", f"{tmpdir}:/sandbox:ro",
                "python:3.11-slim",
                "python", "/sandbox/tool_test.py"
            ]
            
            print(f"[BlastChamber] Triggering Ephemeral Container for Verification...")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return True, result.stdout
                else:
                    return False, f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"
            except subprocess.TimeoutExpired:
                return False, "TIMEOUT: Container execution exceeded 10 seconds."
            except Exception as e:
                return False, f"OS/Docker Execution Error: {str(e)}"

    def _equip_tool(self, filename: str, code: str, schema: str):
        """Permanent commit to organism toolkit."""
        if not filename.endswith(".py"):
            filename += ".py"
            
        target = self.tools_dir / filename
        
        # We append a docstring wrapper locally for parser consumption later
        final_code = f'"""\nSCHEMA: {schema}\n"""\n\n{code}'
        target.write_text(final_code, encoding="utf-8")


if __name__ == "__main__":
    print("[Testing Forge Daemon Natively]")
    forge = EvolutionForge()
    # Simple test task
    forge.synthesize_tool("A script that calculates the 15th number in the Fibonacci sequence and asserts it equals 610.")
