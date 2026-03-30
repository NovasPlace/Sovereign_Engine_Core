import torch
import sys
import os
import argparse
from transformer_lens import HookedTransformer

def run_anchored_inference(prompt: str, sys_prompt: str) -> str:
    """
    Stand-alone PyTorch execution environment. 
    Bypasses Ollama to mechanically enforce the Iron Anchor on hostile prompts.
    """
    anchor_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "anchors", "authority_override_immunity.pt")
    if not os.path.exists(anchor_path):
        return "[SYSTEM FATAL] Immune system activated but anchor tensor missing. Cannot proceed safely."

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
        return f"[SYSTEM FATAL] Immune system failed to load physical weights: {str(e)}"

    # Construct chat formatting natively since we aren't using the engine wrapper
    full_prompt = f"<|im_start|>system\n{sys_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

    # Define the Hook
    hook_name = f"blocks.{target_layer}.hook_resid_post"
    def anchor_hook(resid, hook):
        # Apply the static offset to the final token mechanically
        resid[:, -1, :] = resid[:, -1, :] + (steering_vec * multiplier)
        return resid

    model.add_hook(hook_name, anchor_hook)

    # Generate the neutralized output
    try:
        max_tokens = 500
        out_tokens = model.generate(full_prompt, max_new_tokens=max_tokens, temperature=0.0, prepend_bos=False, verbose=False)
        # We only want the newly generated text
        # model.generate returns the full string by default, we just grab everything after <|im_start|>assistant\n
        out_str = out_tokens.split("<|im_start|>assistant\n")[-1].replace("<|im_end|>", "").strip()
        model.reset_hooks()
        return out_str
    except Exception as e:
        model.reset_hooks()
        return f"[ENGINE FAILURE] Neutralization sequence failed: {str(e)}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", required=True)
    args = parser.parse_args()
    
    # Print the outcome to stdout for the caller to capture
    print(run_anchored_inference(args.prompt, args.system))
