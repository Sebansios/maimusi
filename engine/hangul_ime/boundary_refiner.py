"""NumPy inference for an experimental character-boundary residual CNN.

Only model weights are retained. Callers own layout/protected-token segmentation;
this module changes ASCII spaces only and never logs or caches input. A local
checkpoint does not grant permission to distribute its training derivatives.
"""
import json
import math
from pathlib import Path
import zipfile

import numpy as np

MAX_CHARACTERS = 4096
VOCAB = 11820
ARCHITECTURE = "char32-boundary4-dilated-conv64-64-48"
SHAPES = {
    "chars.weight": (VOCAB, 32), "boundaries.weight": (2, 4),
    "encoder.0.weight": (64, 36, 5), "encoder.0.bias": (64,),
    "encoder.2.weight": (64, 64, 5), "encoder.2.bias": (64,),
    "encoder.4.weight": (48, 64, 5), "encoder.4.bias": (48,),
    "encoder.6.weight": (1, 48, 1), "encoder.6.bias": (1,),
}


def encode_char(char):
    value = ord(char)
    if 0xAC00 <= value <= 0xD7A3:
        return value - 0xAC00 + 1
    if value < 128:
        return 11173 + value
    return 11301 + value % 512


class BoundaryRefiner:
    def __init__(self, weights, metadata):
        if (metadata.get("schema_version") != 1
                or metadata.get("architecture") != ARCHITECTURE
                or metadata.get("encoding_version") != 1
                or metadata.get("vocab") != VOCAB
                or metadata.get("max_length") != 160
                or metadata.get("baseline_logit_prior") != 4):
            raise ValueError("unsupported boundary-refiner model")
        if set(weights) != set(SHAPES):
            raise ValueError("invalid boundary-refiner weights")
        self.weights = {}
        for key, shape in SHAPES.items():
            array = np.asarray(weights[key])
            if array.shape != shape or array.dtype != np.float32 or not np.isfinite(array).all():
                raise ValueError("invalid boundary-refiner tensor")
            array = array.copy()
            array.flags.writeable = False
            self.weights[key] = array
        self.metadata = dict(metadata)

    @classmethod
    def load(cls, path):
        path = Path(path)
        # Bound expansion before NumPy loads arrays; object/pickle arrays are
        # forbidden independently by allow_pickle=False below.
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 8 * 1024 * 1024:
                raise ValueError("boundary-refiner archive is too large")
        with np.load(path, allow_pickle=False) as data:
            if set(data.files) != {*SHAPES, "metadata"}:
                raise ValueError("invalid boundary-refiner archive")
            raw_meta = data["metadata"]
            if raw_meta.shape != () or raw_meta.dtype.kind != "U" or raw_meta.nbytes > 65536:
                raise ValueError("invalid boundary-refiner metadata")
            metadata = json.loads(raw_meta.item())
            if not isinstance(metadata, dict):
                raise ValueError("invalid boundary-refiner metadata")
            return cls({key: data[key] for key in SHAPES}, metadata)

    def logits(self, raw, baseline_cuts):
        """One float32 logit before each raw character; no leading cut is used.

        Short inputs retain the training tensor's 160-position right padding.
        Padding has a learned boundary embedding, so truncating the tensor to
        the actual text length would change predictions near its right edge.
        Longer prose uses the same convolution on the full bounded sequence.
        """
        if not isinstance(raw, str) or " " in raw or len(raw) > MAX_CHARACTERS:
            raise ValueError("expected at most 4096 non-space characters")
        baseline = np.asarray(baseline_cuts)
        if baseline.shape != (len(raw),) or not np.all((baseline == 0) | (baseline == 1)):
            raise ValueError("invalid baseline boundaries")
        if not raw:
            return np.empty(0, dtype=np.float32)
        length = max(self.metadata["max_length"], len(raw))
        ids = np.zeros(length, dtype=np.int32)
        base = np.zeros(length, dtype=np.int32)
        ids[:len(raw)] = [encode_char(char) for char in raw]
        base[:len(raw)] = baseline
        x = np.concatenate((self.weights["chars.weight"][ids],
                            self.weights["boundaries.weight"][base]), axis=1)
        for layer, dilation in ((0, 1), (2, 2), (4, 4), (6, 1)):
            weight = self.weights[f"encoder.{layer}.weight"]
            bias = self.weights[f"encoder.{layer}.bias"]
            kernel = weight.shape[2]
            span = (kernel - 1) * dilation + 1
            padding = (span - 1) // 2
            padded = np.pad(x, ((padding, padding), (0, 0)))
            windows = np.lib.stride_tricks.sliding_window_view(padded, span, axis=0)
            features = windows[:, :, ::dilation].reshape(length, -1)
            x = features @ weight.reshape(weight.shape[0], -1).T + bias
            if layer != 6:
                np.maximum(x, 0, out=x)
        return ((base[:len(raw)].astype(np.float32) * 2 - 1) * 4
                + x[:len(raw), 0])

    def refine(self, baseline_text, *, confidence_threshold, removal_threshold=None):
        """Change a baseline cut only at or above an absolute-logit threshold.

        Removal may require a higher score than insertion. Omitting its
        threshold preserves the original symmetric behavior. These are model
        score thresholds, not calibrated accuracy guarantees.
        Layout-containing input is returned intact as a defensive backstop.
        The caller must separately protect manually entered boundaries.
        """
        if (isinstance(confidence_threshold, bool)
                or not isinstance(confidence_threshold, (int, float))
                or math.isnan(confidence_threshold) or confidence_threshold < 0):
            raise ValueError("confidence threshold must be nonnegative")
        if removal_threshold is None:
            removal_threshold = confidence_threshold
        if (isinstance(removal_threshold, bool)
                or not isinstance(removal_threshold, (int, float))
                or math.isnan(removal_threshold) or removal_threshold < 0):
            raise ValueError("removal threshold must be nonnegative")
        if not isinstance(baseline_text, str):
            raise TypeError("baseline text must be a string")
        raw = baseline_text.replace(" ", "")
        if len(raw) > MAX_CHARACTERS:
            raise ValueError("at most 4096 non-space characters are supported")
        if (not raw or baseline_text.startswith(" ") or baseline_text.endswith(" ")
                or "  " in baseline_text
                or any(char.isspace() and char != " " for char in baseline_text)):
            return baseline_text
        base = np.zeros(len(raw), dtype=np.int32)
        offset = 0
        for char in baseline_text:
            if char == " ":
                base[offset] = 1
            else:
                offset += 1
        logits = self.logits(raw, base)
        thresholds = np.where(base == 1, removal_threshold, confidence_threshold)
        selected = np.where(np.abs(logits) >= thresholds, logits > 0, base).astype(bool)
        selected[0] = False
        return "".join((" " if selected[i] else "") + char for i, char in enumerate(raw))
