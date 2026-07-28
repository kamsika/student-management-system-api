import math
from typing import Iterable


def _as_float_vector(values) -> list[float] | None:
    if not isinstance(values, list) or len(values) != 128:
        return None
    try:
        return [float(v) for v in values]
    except (TypeError, ValueError):
        return None


def average_embeddings(vectors: Iterable[list[float]]) -> list[float] | None:
    """Average multiple 128-d face descriptors into one profile embedding."""
    parsed = []
    for item in vectors:
        vec = _as_float_vector(item)
        if vec:
            parsed.append(vec)
    if not parsed:
        return None

    dim = 128
    sums = [0.0] * dim
    for vec in parsed:
        for index in range(dim):
            sums[index] += vec[index]

    count = float(len(parsed))
    return [value / count for value in sums]


def euclidean_distance(a: list[float], b: list[float]) -> float:
    total = 0.0
    for index in range(min(len(a), len(b))):
        delta = a[index] - b[index]
        total += delta * delta
    return math.sqrt(total)


def find_best_face_match(
    query: list[float],
    candidates: list[dict],
    threshold: float,
) -> dict | None:
    """
    candidates: [{ "student_id": int, "embedding": list[float], ... }, ...]
    Returns the closest match under threshold, or None.
    """
    query_vec = _as_float_vector(query)
    if not query_vec:
        return None

    best = None
    best_distance = threshold

    for item in candidates:
        embedding = _as_float_vector(item.get("embedding") or item.get("face_embedding"))
        if not embedding:
            continue
        distance = euclidean_distance(query_vec, embedding)
        if distance <= best_distance:
            best_distance = distance
            best = {**item, "distance": distance, "confidence": max(0.0, 1.0 - distance / threshold)}

    return best
