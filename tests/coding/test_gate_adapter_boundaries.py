"""Public adapter regressions with test-only port doubles, NOT private-runtime qualification."""
from enum import Enum
import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def boundary(monkeypatch):
    import sys
    shared, ecacc, zone, packages = (ModuleType(name) for name in
        ('shared_contracts', 'packages.ecacc', 'packages.zone_development', 'packages'))
    shared.CriterionResult = Enum('Result', 'PASS FAIL INCONCLUSIVE')
    shared.contract_digest = lambda value: 'bound-request-or-plan'
    def wire(value):
        if getattr(value, 'kind', None) != 'shared-review':
            raise TypeError('Unsupported shared wire value; ECACC artifacts use their own encoder')
        return {'findings': []}
    shared.to_wire = wire
    encoded = []
    def artifact_json(value):
        assert value.kind == 'ecacc-evaluation'
        encoded.append(value)
        return json.dumps({'schema': 'ecacc.v2', 'value': {'result': 'FAIL', 'note': 'x' * 34000}})
    ecacc.canonical_json = artifact_json
    ecacc.VerifierRef = lambda *values: values
    ecacc.EvidenceKind = NS(BEHAVIOR='behavior')
    ecacc.ObligationKind = NS(ACHIEVEMENT='achievement', PRESERVATION='preservation')
    ecacc.VerifierObservation = lambda result, kind, checks=(), note='': NS(result=result, checks=checks, note=note)
    ecacc.Check = lambda name, passed: NS(name=name, passed=passed)
    ecacc.VerifierRegistry = tuple
    zone.Role = NS(VERIFIER='verifier', ARCHITECT='architect', CODER='coder', REVIEWER='reviewer')
    for name in ('RoleIdentity', 'LocalPlan', 'RepairRecipe', 'ChangeProposal', 'FileEdit', 'ReviewReport', 'Finding'):
        setattr(zone, name, lambda **fields: NS(**fields))
    class Delegate:
        def __init__(self, actor, contract, registry):
            self.registry = registry
        def verify(self, context, run_id):
            plugin, = self.registry
            return plugin.verify(None, NS(snapshot=context.source, candidate=context.candidate))
    zone.ECACCVerifier = Delegate
    packages.ecacc = ecacc
    for module in (shared, ecacc, zone, packages):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    source = Path(os.environ.get('AUTOBENCH_ADAPTER_TEST_SOURCE_DIR', ROOT / 'suites/coding'))
    def load(name):
        spec = importlib.util.spec_from_file_location('_test_boundary_' + name, source / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return NS(load=load, results=shared.CriterionResult, encoded=encoded)


class SnapshotPort:
    def __init__(self, tree='exact-tree', size=2100000):
        self.tree = tree
        self.files = (('padding.py', '#' + 'x' * size),)
    def git_tree(self):
        return self.tree
    @property
    def content_digest(self):
        raise AssertionError('Do not serialize large source through the small-message wire codec')


def candidate(ref='candidate-1'):
    return NS(as_ref=lambda: ref)


def test_host_verifier_uses_tree_identity_not_large_content_digest(boundary):
    module = boundary.load('public_verifier')
    source = SnapshotPort()
    scored = []
    def score(files, checks, expected):
        assert files == dict(source.files)
        scored.append(files)
        return {'status': 'FAIL'}
    verifier = module.PublicVerifier(NS(score=score), (), (), object())
    result = verifier.verify(NS(source=source, candidate=candidate()), 'test-run')
    assert len(scored) == 1 and result.result is boundary.results.FAIL
    assert result.checks[0].passed is False


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'ERROR', 'INCONCLUSIVE', None])
def test_host_status_is_never_upgraded(boundary, status):
    plugin = boundary.load('public_verifier').PublicChecks('exact-tree', status, 'candidate-1')
    result = plugin.verify(None, NS(snapshot=SnapshotPort(), candidate=candidate()))
    expected = getattr(boundary.results, status) if status in ('PASS', 'FAIL') else boundary.results.INCONCLUSIVE
    assert result.result is expected


@pytest.mark.parametrize('tree,ref', [('different-tree', 'candidate-1'), ('exact-tree', 'candidate-2')])
def test_foreign_source_or_candidate_cannot_reuse_host_pass(boundary, tree, ref):
    plugin = boundary.load('public_verifier').PublicChecks('exact-tree', 'PASS', 'candidate-1')
    result = plugin.verify(None, NS(snapshot=SnapshotPort(tree), candidate=candidate(ref)))
    assert result.result is boundary.results.INCONCLUSIVE
    assert result.checks == ()


def test_no_observation_cannot_become_pass(boundary):
    plugin = boundary.load('public_verifier').PublicChecks()
    assert plugin.verify(None, NS(snapshot=SnapshotPort(), candidate=candidate())).result is boundary.results.INCONCLUSIVE


def test_repair_uses_ecacc_encoder_and_does_not_truncate_json(boundary):
    coder_type = boundary.load('cycle_roles').Coder
    evaluation = NS(kind='ecacc-evaluation')
    seen = []
    def invoke(files, prompt):
        payload = json.loads(prompt.split('Public deterministic verification: ', 1)[1])
        assert payload['schema'] == 'ecacc.v2' and payload['value']['result'] == 'FAIL'
        assert len(payload['value']['note']) == 34000
        seen.append(prompt)
        return {}, {**files, 'core.py': 'fixed\n'}
    context = NS(source=NS(files=(('core.py', 'broken\n'),)), source_ref='current-source',
        request=NS(objective='Repair the bug'), plan=NS(steps=('Repair',), target_paths=('core.py',)),
        review=NS(kind='shared-review'), evaluation=evaluation)
    proposal = coder_type(NS(invoke=invoke)).code(context)
    assert boundary.encoded == [evaluation] and len(seen) == 1
    assert proposal.source == 'current-source' and proposal.edits[0].content == 'fixed\n'
