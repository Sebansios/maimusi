"""Torch/NumPy parity on seeded synthetic inputs only; never reads test corpora."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
from hangul_ime.boundary_refiner import BoundaryRefiner, encode_char


def verify(checkpoint, exported):
    import torch
    torch.set_num_threads(2)
    spec = importlib.util.spec_from_file_location("training", ROOT / "tools/train_boundary_residual.py")
    training = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(training)
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    reference = training.make_model().eval()
    reference.load_state_dict(payload["state_dict"])
    refiner = BoundaryRefiner.load(exported)
    rng = np.random.default_rng(20261002)
    alphabet = list("가각나한글띄어쓰기ABCxyz019.,!?é🙂ㅋㅋㅠㅠᆫ")
    cases = ["한글입력기를정확하게만들어보자", "기다리게해서미안해욤", "가", ""]
    cases += ["".join(rng.choice(alphabet, size=int(rng.integers(1, 161)))) for _ in range(512)]
    cases += ["한글입력🙂ABC" * (length // 8) + "가" * (length % 8)
              for length in (159, 160, 161, 255, 512, 1024, 2048, 4096)]
    maximum = 0.
    threshold_mismatches = 0
    for raw in cases:
        assert all(encode_char(c) == training.encode_char(c) for c in raw)
        length = max(160, len(raw))
        ids = np.zeros((1, length), dtype=np.int64)
        base = np.zeros((1, length), dtype=np.int64)
        ids[0, :len(raw)] = [encode_char(c) for c in raw]
        base[0, :len(raw)] = rng.integers(0, 2, size=len(raw))
        if raw: base[0, 0] = 0
        with torch.no_grad():
            expected = reference(torch.from_numpy(ids), torch.from_numpy(base)).numpy()[0, :len(raw)]
        actual = refiner.logits(raw, base[0, :len(raw)])
        if raw: maximum = max(maximum, float(np.max(np.abs(expected - actual))))
        np.testing.assert_allclose(actual, expected, rtol=2e-5, atol=2e-5)
        for threshold in (0., 1., 3., 6., 8.):
            before = base[0, :len(raw)]
            torch_cuts = np.where(np.abs(expected) >= threshold, expected > 0, before)
            numpy_cuts = np.where(np.abs(actual) >= threshold, actual > 0, before)
            threshold_mismatches += int(np.sum(torch_cuts != numpy_cuts))
        baseline_text = "".join((" " if base[0, i] else "") + c for i, c in enumerate(raw))
        assert refiner.refine(baseline_text, confidence_threshold=3).replace(" ", "") == raw
    if threshold_mismatches:
        raise AssertionError("threshold decision parity failed")
    return dict(passed=True, cases=len(cases), maximum_absolute_logit_error=maximum,
                threshold_decision_mismatches=threshold_mismatches,
                longest_input=max(map(len, cases)), checkpoint_epoch=payload.get("epoch"),
                note="Seeded synthetic/authored input only; no train/dev/test text read.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("exported", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.checkpoint, args.exported)
    text = json.dumps(report, indent=2) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
