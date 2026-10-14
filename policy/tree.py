from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from policy.base import FEATURE_NAMES

MAX_DEPTH = 4

MIN_SAMPLES_LEAF = 5

@dataclass
class TreeNode:
    feature_index: Optional[int] = None
    threshold: Optional[float] = None
    left: Optional["TreeNode"] = None
    right: Optional["TreeNode"] = None
    prediction: Optional[str] = None

def _gini(labels: list[str]) -> float:
    if not labels:
        return 0.0
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    n = len(labels)
    return 1.0 - sum((count / n) ** 2 for count in counts.values())

def _majority_label(labels: list[str]) -> str:
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return max(counts, key=lambda label: (counts[label], label))

def _gini_counts(counts: dict[str, int], n: int) -> float:
    if n == 0:
        return 0.0
    return 1.0 - sum((count / n) ** 2 for count in counts.values())

def _best_split(
    rows: list[tuple[tuple[float, ...], str]]
) -> Optional[tuple[int, float, float]]:
    labels = [label for _, label in rows]
    n = len(rows)
    parent_gini = _gini(labels)
    total: dict[str, int] = {}
    for label in labels:
        total[label] = total.get(label, 0) + 1
    n_features = len(rows[0][0])
    best: Optional[tuple[int, float, float]] = None

    for feature_index in range(n_features):
        ordered = sorted(rows, key=lambda r: r[0][feature_index])
        left: dict[str, int] = {label: 0 for label in total}
        for i in range(n - 1):
            left[ordered[i][1]] += 1
            value, next_value = ordered[i][0][feature_index], ordered[i + 1][0][feature_index]
            if value == next_value:
                continue
            n_left = i + 1
            n_right = n - n_left
            if n_left < MIN_SAMPLES_LEAF or n_right < MIN_SAMPLES_LEAF:
                continue
            right = {label: total[label] - left[label] for label in total}
            weighted = (
                n_left / n * _gini_counts(left, n_left)
                + n_right / n * _gini_counts(right, n_right)
            )
            if weighted < parent_gini and (best is None or weighted < best[2]):
                best = (feature_index, (value + next_value) / 2.0, weighted)
    return best

def fit(rows: list[tuple[tuple[float, ...], str]], *, depth: int = 0) -> TreeNode:
    if not rows:
        raise ValueError("fit() requires at least one training row")
    labels = [label for _, label in rows]
    if depth >= MAX_DEPTH or len(set(labels)) == 1:
        return TreeNode(prediction=_majority_label(labels))

    split = _best_split(rows)
    if split is None:
        return TreeNode(prediction=_majority_label(labels))

    feature_index, threshold, _ = split
    left_rows = [(f, label) for f, label in rows if f[feature_index] <= threshold]
    right_rows = [(f, label) for f, label in rows if f[feature_index] > threshold]
    return TreeNode(
        feature_index=feature_index, threshold=threshold,
        left=fit(left_rows, depth=depth + 1), right=fit(right_rows, depth=depth + 1),
    )

def predict(node: TreeNode, features: tuple[float, ...]) -> str:
    if node.prediction is not None:
        return node.prediction
    if features[node.feature_index] <= node.threshold:
        return predict(node.left, features)
    return predict(node.right, features)

def export_if_else(node: TreeNode) -> str:
    return "def predict_exported(features):\n" + _export_body(node, indent=1)

def _export_body(node: TreeNode, *, indent: int) -> str:
    pad = "    " * indent
    if node.prediction is not None:
        return f"{pad}return {node.prediction!r}\n"
    name = FEATURE_NAMES[node.feature_index]
    return (
        f"{pad}if features[{name!r}] <= {node.threshold!r}:\n"
        f"{_export_body(node.left, indent=indent + 1)}"
        f"{pad}else:\n"
        f"{_export_body(node.right, indent=indent + 1)}"
    )

def export_text(node: TreeNode) -> str:
    return _export_text(node, depth=0)

def _export_text(node: TreeNode, *, depth: int) -> str:
    pad = "|   " * depth + "|--- "
    if node.prediction is not None:
        return f"{pad}class: {node.prediction}\n"
    name = FEATURE_NAMES[node.feature_index]
    return (
        f"{pad}{name} <= {node.threshold:.4g}\n"
        f"{_export_text(node.left, depth=depth + 1)}"
        f"{pad}{name} >  {node.threshold:.4g}\n"
        f"{_export_text(node.right, depth=depth + 1)}"
    )

class TreePolicy:

    def __init__(self, root: TreeNode) -> None:
        self._root = root

    def decide(self, features, context=None) -> str:
        return predict(self._root, features.as_tuple())

def train(rows) -> TreePolicy:
    data = [(row.features.as_tuple(), row.label) for row in rows]
    root = fit(data)
    return TreePolicy(root)
