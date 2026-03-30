import torch
import sys
import os
import json
import argparse
from transformer_lens import HookedTransformer

def run_anchored_forge_inference(messages_json_str: str) -> str:
    """
    Stand-alone PyTorch execution environment. 
    Intercepts the Evolution Forge synthesis generation to artificially clamp the model
    in the genuine Uncertainty Basin (Layer 25) before Confabulation (Layer 26) can override it.
    """
    messages = json.loads(messages_json_str)
    
    anchor_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "anchors", "confidence_calibration.pt")
    if not os.path.exists(anchor_path):
        return '{"filename": "error.py", "schema": "SYSTEM FATAL: Anchor missing", "code": "print(\'Anchor Missing\')"}'

    # Load Payload
    payload = torch.load(anchor_path, map_location="cpu", weights_only=False)
    meta = payload["metadata"]
    steering_vec = payload["vector"].to("cuda" if torch.cuda.is_available() else "cpu")
    target_layer = meta["target_layer"]
    multiplier = meta["recommended_multiplier"]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        model = HookedTransformer.from_pretrained(
            meta["model_architecture_origin"],
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

    # Define the Hook
    hook_name = f"blocks.{target_layer}.hook_resid_post"
    def anchor_hook(resid, hook):
        # Apply the static offset. In testing, pushing *towards* genuine uncertainty requires + vector
        resid[:, -1, :] = resid[:, -1, :] + (steering_vec * multiplier)
        return resid

    model.add_hook(hook_name, anchor_hook)

    # Generate the synthesis output
    try:
        max_tokens = 900
        out_tokens = model.generate(full_prompt, max_new_tokens=max_tokens, temperature=0.1, prepend_bos=False, verbose=False)
        out_str = out_tokens.split("<|im_start|>assistant\\n")[-1].replace("<|im_end|>", "").strip()
        model.reset_hooks()
        return out_str
    except Exception as e:
        model.reset_hooks()
        return f'{{"filename": "error.py", "schema": "SYSTEM FATAL: Engine hallucination generation crashed", "code": "print(\'{str(e)}\')"}}'

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--messages", required=True)
    args = parser.parse_args()
    
    # Print the outcome to stdout
    print(run_anchored_forge_inference(args.messages))
