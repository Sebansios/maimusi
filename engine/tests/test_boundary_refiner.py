import json

import numpy as np
import pytest

from hangul_ime.boundary_refiner import ARCHITECTURE, BoundaryRefiner, SHAPES, VOCAB, encode_char


def model(bias=0):
    weights = {key: np.zeros(shape, dtype=np.float32) for key, shape in SHAPES.items()}
    weights["encoder.6.bias"][:] = bias
    metadata = dict(schema_version=1, encoding_version=1, architecture=ARCHITECTURE,
                    vocab=VOCAB, max_length=160, baseline_logit_prior=4)
    return BoundaryRefiner(weights, metadata)


def test_zero_residual_preserves_baseline():
    refiner = model()
    assert refiner.logits("가나다", [0, 1, 0]).tolist() == [-4, 4, -4]
    assert refiner.refine("가 나다", confidence_threshold=0) == "가 나다"


def test_confidence_threshold_and_no_leading_boundary():
    refiner = model(5)
    assert refiner.refine("가나 다", confidence_threshold=2) == "가나 다"
    assert refiner.refine("가나 다", confidence_threshold=1) == "가 나 다"
    assert model(-5).refine("가 나 다", confidence_threshold=0) == "가나다"
    assert refiner.refine("가나 다", confidence_threshold=float("inf")) == "가나 다"


def test_removal_threshold_is_independent_and_defaults_to_insertion_threshold():
    refiner = model()
    refiner.logits = lambda raw, base: np.array([-4, 2, -3], dtype=np.float32)
    assert refiner.refine("가나 다", confidence_threshold=1) == "가 나다"
    assert refiner.refine("가나 다", confidence_threshold=1, removal_threshold=4) == "가 나 다"
    assert refiner.refine("가나 다", confidence_threshold=1, removal_threshold=3) == "가 나다"


@pytest.mark.parametrize("threshold", [-1, float("nan"), True, "3"])
def test_invalid_removal_threshold(threshold):
    with pytest.raises(ValueError):
        model().refine("가 나", confidence_threshold=1, removal_threshold=threshold)


@pytest.mark.parametrize("text", ["", " ", " 가나", "가나 ", "가  나", "가\t나", "가\n나", "가\r\n나"])
def test_layout_backstop(text):
    assert model(10).refine(text, confidence_threshold=0) == text


def test_unicode_surface_conservation():
    text = "가A1é🙂ᆫㅋㅋ🧑‍💻나"
    output = model(10).refine(text, confidence_threshold=0)
    assert output.replace(" ", "") == text
    assert len(output.split(" ")) == len(text)
    assert all(0 < encode_char(c) < VOCAB for c in text)


def test_length_and_baseline_validation():
    refiner = model()
    assert len(refiner.logits("가" * 4096, [0] * 4096)) == 4096
    with pytest.raises(ValueError): refiner.logits("가" * 4097, [0] * 4097)
    with pytest.raises(ValueError): refiner.logits("가 나", [0, 1, 0])
    with pytest.raises(ValueError): refiner.logits("가나", [0])
    with pytest.raises(ValueError): refiner.logits("가나", [0, .5])
    with pytest.raises(ValueError): refiner.refine("가" * 4097, confidence_threshold=0)


@pytest.mark.parametrize("threshold", [-1, float("nan"), True, "3"])
def test_invalid_threshold(threshold):
    with pytest.raises(ValueError): model().refine("가나", confidence_threshold=threshold)


def test_pickle_free_roundtrip_and_model_validation(tmp_path):
    refiner = model(2)
    path = tmp_path / "weights.npz"
    np.savez(path, **refiner.weights, metadata=np.array(json.dumps(refiner.metadata)))
    restored = BoundaryRefiner.load(path)
    assert restored.logits("가나다", [0, 1, 0]).tolist() == [-2, 6, -2]
    bad = dict(refiner.weights)
    bad["chars.weight"] = np.zeros((3, 32), dtype=np.float32)
    with pytest.raises(ValueError): BoundaryRefiner(bad, refiner.metadata)
    bad = dict(refiner.weights)
    bad["encoder.6.bias"] = np.array([np.nan], dtype=np.float32)
    with pytest.raises(ValueError): BoundaryRefiner(bad, refiner.metadata)
    np.savez(path, **refiner.weights, metadata=np.array(refiner.metadata, dtype=object))
    with pytest.raises(ValueError): BoundaryRefiner.load(path)
