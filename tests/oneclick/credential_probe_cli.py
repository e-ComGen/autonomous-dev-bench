"""TEST ONLY: command boundary probe copied into a temporary CLI, never shipped as production CLI."""
import json
import os
import sys
from benchmark_core.execution import CommandSpec, ProcessRunner
from corpus.discovery.github import GitHubReader, IntakeError
from corpus.qualification.policy import IssuePolicy
from suites.coding.settings import Settings
from suites.coding.spend import authorize
from suites.coding.backends.environment import private_environment
from tools.launch import command_name
from tools.launcher_env import clean_environment

KEYS = ('GITHUB_TOKEN', 'GH_TOKEN', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'OTHER_SECRET')


def main(root):
    command = command_name(sys.argv[1:])
    observed = {'command': command, 'host': {key: bool(os.environ.get(key)) for key in KEYS},
                'github_error': None, 'provider_error': None, 'github_matches': False,
                'provider_matches': False, 'api_requests': 0, 'model_called': False,
                'docker_config_present': bool(os.environ.get('DOCKER_CONFIG'))}
    if command in {'ab', 'ab-preflight', 'qualify', 'discover'}:
        try:
            # Construct the real client but never issue an HTTP request.
            reader = GitHubReader(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or '',
                                  None, IssuePolicy())
            observed['github_matches'] = reader._token == 'unit-only-host-github'
            observed['api_requests'] = reader.requests
        except IntakeError as error:
            observed['github_error'] = str(error)
    if command == 'ab':
        try:
            # Admission only; no relay, transport or model call is created.
            observed['provider_matches'] = authorize(Settings(), 2, True) == 'unit-only-host-provider'
        except ValueError as error:
            observed['provider_error'] = str(error)
    script = 'import os,json; print(json.dumps({key:bool(os.environ.get(key)) for key in ' + repr(KEYS) + '}))'
    runner = ProcessRunner()
    observed['children'] = {}
    try:
        for label, environment in (
                ('bootstrap', clean_environment(root)),
                ('native', private_environment(root / 'child-home', sys.executable, root))):
            result = runner.run(CommandSpec((sys.executable, '-I', '-B', '-c', script), 20,
                                           str(root), environment, inherit_environment=False))
            if not result.succeeded:
                raise AssertionError('TEST_CHILD_FAILED')
            observed['children'][label] = json.loads(result.stdout)
    finally:
        runner.cancel_running()
    (root / 'observed.json').write_text(json.dumps(observed, indent=2), encoding='utf-8')
    return 0
