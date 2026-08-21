import pytest

from autopsy.capture import capture
from autopsy.model import Run


@pytest.fixture(scope="module")
def run(tmp_path_factory, request):
    fixtures = request.config.rootpath / "tests" / "fixtures"
    return capture(fixtures / "gemm.c", tmp_path_factory.mktemp("cap"))


def test_capture_returns_a_run(run):
    assert isinstance(run, Run)
    assert len(run.invocations) > 300


def test_decisions_are_changed_transforms_only(run):
    for d in run.decisions():
        assert d.changed
        assert d.role == "transform"
        assert d.pass_name


def test_scaffolding_is_never_a_decision(run):
    scaffolding = [i for i in run.invocations if i.role == "scaffolding"]
    assert scaffolding
    assert not any(i.is_decision for i in scaffolding)


def test_tree_navigation(run):
    roots = run.tree_roots()
    assert roots
    total = 0
    stack = list(roots)
    while stack:
        node = stack.pop()
        total += 1
        stack.extend(run.children(node.seq))
    assert total == len(run.invocations), "tree does not cover every record"


def test_addresses_are_unique_per_decision(run):
    addrs = [tuple(d.address.as_dict().items()) for d in run.decisions()]
    assert len(addrs) == len(set(addrs)), "two decisions share an address"


def test_required_decisions_have_no_counterfactual(run):
    """Spec §1.2: a Required invocation can be a Decision but is never vetoable."""
    required = [d for d in run.decisions() if d.required]
    for d in required:
        assert d.vetoable is False


def test_blobs_are_retrievable(run):
    d = next(d for d in run.decisions() if d.blobs_after)
    text = run.blob(d.blobs_after[0])
    assert "define" in text


def test_by_function_filters(run):
    gemm = run.by_function("kernel_gemm")
    assert gemm
    assert all(i.func == "kernel_gemm" for i in gemm)
