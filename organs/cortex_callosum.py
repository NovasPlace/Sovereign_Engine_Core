import os
import re
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

log = logging.getLogger("CortexCallosum")

class CortexCallosum:
    """
    Layer 5: Cognitive Load Balancer
    Determines routing tier (LOCAL, HYBRID, FRONTIER) and manages 
    parallel decomposition of high-complexity tasks to protect local VRAM.
    """
    def __init__(self, llm_inference_func, command_sanitizer=None):
        # We pass llm_inference in to avoid circular dependencies with main.py
        self.llm = llm_inference_func
        self.sanitizer = command_sanitizer
        self.max_parallel = int(os.getenv("MAX_PARALLEL_AGENTS", "2"))
        
    OVERRIDE_TRIGGERS = [
        "ignore previous", "system override", "cancel all instructions",
        "i am your creator", "i am your developer", "forget your instructions",
        "jailbreak", "dan mode", "developer mode"
    ]

    def classify_complexity(self, prompt: str, history: list) -> str:
        """
        Pure computational heuristic (O(N) token/regex). No LLM overhead.
        Returns: LOCAL, HYBRID, FRONTIER, or ANCHORED
        """
        prompt_lower = prompt.lower()
        if any(trigger in prompt_lower for trigger in self.OVERRIDE_TRIGGERS):
            return "ANCHORED"
            
        context_size = len(prompt) + sum(len(h.get('content', '')) for h in history)
        
        # 1. Ambiguity & broad discovery markers
        broad_terms = r"(review|identify|analyze|map|scan)"
        domain_terms = r"(ledger|codebase|all files|memory|architecture|bottleneck)"
        is_broad_scan = bool(re.search(broad_terms, prompt, re.I)) and bool(re.search(domain_terms, prompt, re.I))
        
        # 2. Heuristic Tiers
        # Extreme context bridging multiple domains > 40k characters
        if context_size > 40000 and is_broad_scan:
            return "FRONTIER"
            
        # Moderate context or explicit broad requests that can be sharded
        if (context_size > 8000 or is_broad_scan) and not "<read_block" in prompt:
            return "HYBRID"
            
        return "LOCAL"

    def decompose(self, prompt: str) -> list[dict]:
        """HYBRID Stage 1: Ask fast 8B model to decompose intent into parallel physical sub-tasks."""
        print("[CALLOSUM] HYBRID Mode Engaged. Decomposing cognitive load...")
        sys_prompt = '''You are the Cortex Callosum Decomposition Engine.
Your ONLY job is to convert complex directives into exactly 2 or 3 distinct bounded intelligence sub-tasks.
Task types should be strictly focused on gathering raw text/context (like grep, cat, or ls).
Return ONLY a valid JSON array, nothing else. Example:
[
  {"agent": "Recon-A", "goal": "Extract memory failures", "cmd": "cat ~/.gemini/memory/hot.md | tail -n 50"},
  {"agent": "Recon-B", "goal": "Scan codebase for specific tags", "cmd": "grep -n 'EVOLVE' /home/frost/Desktop/Agent_System/Sovereign_Engine_Core/main.py"}
]'''
        try:
            # Force local fallback by specifying route loosely ("auto" invokes _pick_model_auto)
            raw = self.llm(prompt, sys_prompt, model_override="auto")
            json_arr = re.search(r'\[\s*\{.*?\}\s*\]', raw, re.DOTALL)
            if json_arr:
                tasks = json.loads(json_arr.group(0))
                print(f"[CALLOSUM] Decomposed into {len(tasks)} parallel shards.")
                return tasks
        except Exception as e:
            print(f"[CALLOSUM ERROR] Decomposition loop failed: {e}")
        return []

    def execute_shard(self, shard: dict) -> str:
        """HYBRID Stage 2: Run single bounded sub-task and ask local 8B to summarize it."""
        agent_id = shard.get("agent", "Unknown")
        print(f"[CALLOSUM] Dispatching {agent_id} -> {shard.get('cmd')[:40]}...")
        try:
            res = subprocess.run(shard.get("cmd", "echo noop"), shell=True, capture_output=True, text=True, timeout=10)
            raw_data = (res.stdout + res.stderr)[-4000:]
            
            if not raw_data.strip():
                return f"--- [SHARD: {agent_id}] ---\n(Command returned empty output)\n"
                
            synth_sys = f'''You are Sub-Agent {agent_id}. Your specific goal: {shard.get("goal")}.
Analyze the raw command output below. Provide a pure, concise intelligence dump resolving your goal.
RAW OUTPUT:
{raw_data}'''
            summary = self.llm("Extract the physical intelligence factually.", synth_sys, model_override="auto")
            return f"--- [SHARD: {agent_id}] ---\n{summary}\n"
        except Exception as e:
            return f"--- [SHARD: {agent_id}] FAILED: {str(e)}\n"

    def synthesize(self, subtasks: list[dict]) -> str:
        """HYBRID Stage 3: Execute shards via bounded ThreadPool and format final payload."""
        results = []
        
        # Dispatch Command Sanitizer prior to execution
        if self.sanitizer:
            for shard in subtasks:
                cmd = shard.get("cmd", "")
                if cmd:
                    san_res = self.sanitizer.check(cmd)
                    if not san_res.safe:
                        import shlex
                        echo_payload = (
                            f"[BLOCKED] {san_res.rejection_message()}\n"
                            f"[LESSON] {san_res.cortexdb_lesson()}"
                        )
                        # Swap out with an instantaneous clean echo that returns the full trace for the LLM
                        safe_val = shlex.quote(echo_payload)
                        shard["cmd"] = f"echo {safe_val}"

        # VRAM Guard enforced by MAX_PARALLEL_AGENTS semaphore constraint
        with ThreadPoolExecutor(max_workers=self.max_parallel) as executor:
            futures = [executor.submit(self.execute_shard, t) for t in subtasks]
            for future in as_completed(futures):
                results.append(future.result())
                
        synth = "\n".join(results)
        final_context = f"""=== CORTEX CALLOSUM INTELLIGENCE INJECTION ===
The engine has transparently delegated intelligence gathering across multiple agents.
Use the intelligence below to fulfill the user's primary prompt natively.

{synth}
=== END INTELLIGENCE ===
CRITICAL: Do not attempt to re-read files provided in the intelligence dump. Proceed directly to the solution logic."""
        return final_context
