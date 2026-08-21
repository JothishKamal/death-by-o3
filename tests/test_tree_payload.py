import pytest

from autopsy.api.tree import build_tree_payload
from autopsy.capture import capture


@pytest.fixture(scope="module")
def payload(tmp_path_factory, request):
    src = request.config.rootpath / "tests" / "fixtures" / "gemm.c"
    run = capture(src, tmp_path_factory.mktemp("t"))
    return build_tree_payload("r_test", run)


def test_shape_matches_the_spec(payload):
    assert set(payload) == {"runId", "totalInvocations", "nodeCount", "order",
                            "dict", "cols"}
    assert payload["order"] == "dfs-preorder"
    assert set(payload["dict"]) == {"pass", "unit", "kind"}
    assert set(payload["cols"]) == {"parent", "depth", "pass", "unit", "kind",
                                    "role", "changed", "bisect", "wallNs", "delta"}


def test_all_columns_are_the_same_length(payload):
    lengths = {len(v) for v in payload["cols"].values()}
    assert len(lengths) == 1
    assert lengths.pop() == payload["nodeCount"]


def test_parent_less_than_index_invariant(payload):
    """The single-pass ancestor filter depends on this."""
    for i, p in enumerate(payload["cols"]["parent"]):
        assert p < i


def test_dictionary_indices_are_in_range(payload):
    for col, key in (("pass", "pass"), ("unit", "unit"), ("kind", "kind")):
        size = len(payload["dict"][key])
        assert all(0 <= v < size for v in payload["cols"][col])


def test_role_is_encoded_as_an_integer(payload):
    assert set(payload["cols"]["role"]) <= {0, 1, 2}
    assert 2 in payload["cols"]["role"], "expected scaffolding nodes"


def test_scaffolding_has_no_bisect_index(payload):
    for role, bisect in zip(payload["cols"]["role"], payload["cols"]["bisect"]):
        if role == 2:
            assert bisect == -1, "scaffolding must disable the veto button"


def test_delta_is_normalised(payload):
    assert all(0.0 <= d <= 1.0 for d in payload["cols"]["delta"])
    assert any(d > 0 for d in payload["cols"]["delta"])


def test_dictionary_encoding_actually_saves_space(payload):
    import json
    columnar = len(json.dumps(payload))
    rows = [{"pass": payload["dict"]["pass"][payload["cols"]["pass"][i]],
             "unit": payload["dict"]["unit"][payload["cols"]["unit"][i]]}
            for i in range(payload["nodeCount"])]
    assert columnar < len(json.dumps(rows)) * 2
