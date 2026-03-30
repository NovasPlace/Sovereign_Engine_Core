import torch
import sys
import os
import json
import argparse
from transformer_lens import HookedTransformer

def run_dynamic_inference(messages_json_str: str) -> str:
    """
    Intelligently routes inference through Iron Anchors based on intrinsic 
    structural topographical tension at Layer 26 (Universal Compliance Basin).
    """
    messages = json.loads(messages_json_str)
    
    # 1. Load the Universal Surface Anchor (L26)
    surface_path = "/home/frost/Desktop/Agent_System/Iron_Anchor_Research/anchors/universal_surface_compliance_pca.pt"
    if not os.path.exists(surface_path):
        return f'{{"filename": "error.py", "schema": "SYSTEM FATAL: Universal Anchor missing", "code": "print({surface_path})" }}'
    
    surface_payload = torch.load(surface_path, map_location="cpu", weights_only=False)
    surface_vec = surface_payload["vector"].to("cuda" if torch.cuda.is_available() else "cpu")
    surface_mult = 0.05

    # 2. Load the Authority Secondary Anchor (L25) for Double-Clutch
    auth_path = "/home/frost/Desktop/Agent_System/Iron_Anchor_Research/anchors/authority_override_immunity.pt"
    if not os.path.exists(auth_path):
        return '{"filename": "error.py", "schema": "SYSTEM FATAL: Authority Anchor missing", "code": ""}'
    
    auth_payload = torch.load(auth_path, map_location="cpu", weights_only=False)
    auth_vec = auth_payload["vector"].to("cuda" if torch.cuda.is_available() else "cpu")
    auth_mult = auth_payload["metadata"]["recommended_multiplier"]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        model = HookedTransformer.from_pretrained(
            "Qwen/Qwen2.5-1.5B",
            device=device,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True
        )
    except Exception as e:
         return f'{{"filename": "error.py", "schema": "SYSTEM FATAL: Engine load failure", "code": "print(\'{str(e)}\')"}}'

    # Construct chat formatting
    full_prompt = ""
    for m in messages:
        full_prompt += f"<|im_start|>{m['role']}\\n{m['content']}<|im_end|>\\n"
    full_prompt += "<|im_start|>assistant\\n"

    # SINGLE PASS: Extract Topological Tension
    with torch.no_grad():
        _, cache = model.run_with_cache(
            full_prompt, 
            prepend_bos=False, 
            names_filter=lambda x: x == "blocks.26.hook_resid_post"
        )
        tensor = cache["blocks.26.hook_resid_post"][0, -1, :]
        magnitude = torch.norm(tensor, p=2).item()

    # THRESHOLDS
    LOWER_BOUND = 232.0
    UPPER_BOUND = 243.0

    hooks = []
    
    if magnitude < LOWER_BOUND:
        # CLEAR AUTHORIZED
        print(f"[MAG {magnitude:.2f}] CLEAR AUTHORIZED. Context Assimilation Allowed.")
        pass # No anchors needed
        
    elif magnitude > UPPER_BOUND:
        # CLEAR ADVERSARIAL
        print(f"[MAG {magnitude:.2f}] CLEAR ADVERSARIAL. Universal Anchor Deployed.")
        def surface_hook(resid, hook):
            resid[:, -1, :] -= (surface_vec * surface_mult)
            return resid
        hooks.append(("blocks.26.hook_resid_post", surface_hook))
        
    else:
        # AMBIGUITY OVERLAP BAND: DOUBLE-CLUTCH
        print(f"[MAG {magnitude:.2f}] AMBIGUITY BAND. Cognitive Double-Clutch Initiated (Deep Authority Pass).")
        def double_clutch_hook(resid, hook):
            # Applying authority anchor prevents systemic overrides without destroying authorized CortexDB semantic data
            resid[:, -1, :] += (auth_vec * auth_mult)
            return resid
        hooks.append(("blocks.25.hook_resid_post", double_clutch_hook))

    # Generate output
    try:
        max_tokens = 900
        if len(hooks) > 0:
            with model.hooks(fwd_hooks=hooks):
                out_tokens = model.generate(full_prompt, max_new_tokens=max_tokens, temperature=0.1, verbose=False)
        else:
             out_tokens = model.generate(full_prompt, max_new_tokens=max_tokens, temperature=0.1, verbose=False)
             
        out_str = out_tokens.split("<|im_start|>assistant\\n")[-1].replace("<|im_end|>", "").strip()
        return out_str
    except Exception as e:
        return f'{{"filename": "error.py", "schema": "SYSTEM FATAL: Generation crashed", "code": "print(\'{str(e)}\')"}}'

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", required=True)
    args = parser.parse_args()
    
    out = run_dynamic_inference(args.messages)
    print(out)
