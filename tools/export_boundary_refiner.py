"""Export a trusted local research checkpoint to pickle-free NumPy weights.

This conversion grants no permission to redistribute training-derived weights.
PyTorch is required only for export, never by the runtime refiner.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from hangul_ime.boundary_refiner import ARCHITECTURE, BoundaryRefiner, SHAPES, VOCAB


def export_checkpoint(checkpoint, output, *, confidence_threshold=1.3, removal_threshold=None):
    import torch
    if (isinstance(confidence_threshold, bool)
            or not math.isfinite(confidence_threshold) or confidence_threshold < 0):
        raise ValueError("confidence threshold must be finite and nonnegative")
    if removal_threshold is not None and (isinstance(removal_threshold, bool)
            or not math.isfinite(removal_threshold) or removal_threshold < 0):
        raise ValueError("removal threshold must be finite and nonnegative")
    checkpoint, output = Path(checkpoint), Path(output)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if (payload.get("architecture") != ARCHITECTURE or payload.get("vocab") != VOCAB
            or payload.get("max_length") != 160):
        raise ValueError("unsupported checkpoint architecture")
    state = payload["state_dict"]
    if set(state) != set(SHAPES):
        raise ValueError("unexpected checkpoint tensors")
    arrays = {key: value.detach().cpu().numpy() for key, value in state.items()}
    metadata = {
        "schema_version": 1, "encoding_version": 1,
        "architecture": ARCHITECTURE, "vocab": VOCAB, "max_length": 160,
        "baseline_logit_prior": 4, "epoch": payload.get("epoch"),
        "confidence_threshold": float(confidence_threshold),
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "trainer_sha256": payload.get("trainer_sha256"),
        "training_cache_sha256": payload.get("training_cache_sha256"),
        "development_cache_sha256": payload.get("development_cache_sha256"),
        "purpose": "restricted local research; source permissions required for public release",
    }
    if removal_threshold is not None:
        metadata["removal_threshold"] = float(removal_threshold)
    BoundaryRefiner(arrays, metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        np.savez_compressed(handle, **arrays, metadata=np.array(json.dumps(metadata)))
    BoundaryRefiner.load(output)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--threshold", type=float, default=1.3)
    parser.add_argument("--removal-threshold", type=float)
    args = parser.parse_args()
    print(json.dumps(export_checkpoint(args.checkpoint, args.output,
                                      confidence_threshold=args.threshold,
                                      removal_threshold=args.removal_threshold)))


if __name__ == "__main__":
    main()
