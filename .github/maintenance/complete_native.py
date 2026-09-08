"""Apply bounded reviewed source edits in CI; the published branch contains the resulting files."""
from pathlib import Path
import hashlib
import json

BASE = '49a5f0844a4e2caf577d42b9c56b07bfe6651a4b'


def change(path, replacements):
    target = Path(path)
    source = target.read_text(encoding='utf-8')
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('Unexpected source at ' + path + ': ' + before[:80])
        source = source.replace(before, after)
    target.write_text(source, encoding='utf-8', newline='\n')


def apply():
    change('corpus/qualification/policy.py', [
        ('max_file_bytes: int = 4194304', 'max_file_bytes: int = 16777216'),
        ('max_code_bytes: int = 900000', 'max_code_bytes: int = 16777216'),
        ('"max_code_bytes": (1024, 900000)', '"max_code_bytes": (1024, 33488896)')])
    change('suites/coding/cycle_request.py', [
        ('max_source_bytes=1000000', 'max_source_bytes=33554432')])
    change('suites/coding/source.py', [
        ('if path.stat().st_size > 1000000:', 'if path.stat().st_size > 16777216:'),
        ('path.read_text(encoding="utf-8")\n    if sum(len(value.encode()) for value in result.values()) > 1000000:',
         'path.read_bytes().decode("utf-8")\n    if sum(len(value.encode()) for value in result.values()) > 33554432:'),
        ('The current ADCP source projection is limited to 1,000,000 bytes',
         'The allocated ADCP source projection is limited to 32 MiB')])
    change('corpus/qualification/workspace.py', [
        ('if not path.is_file() or path.stat().st_size > 4194304:',
         'before = base64.b64decode(record["data"], validate=True)\n            if not path.is_file() or path.stat().st_size > max(len(before), self.max_patch_bytes):'),
        ('            before = base64.b64decode(record["data"])\n', '')])
    change('tools/stage_ab_runtime.py', [
        ('from suites.coding.adcp_loading import ADCP_COMMIT, load_adcp',
         'from suites.coding.adcp_loading import ADCP_COMMIT, load_adcp, verify_distribution'),
        ('relative.parts[0] not in {"packages", "docs"}', 'relative.parts[0] not in {"packages", "docs", "tests"}'),
        ('    args = parser.parse_args()\n    stage(args.source, ROOT / ".bench/adcp")\n    print(json.dumps(load_adcp(ROOT)))',
         '    parser.add_argument("--target", default=str(ROOT / ".bench/adcp"))\n    args = parser.parse_args()\n    stage(args.source, Path(args.target))\n    verify_distribution(Path(args.target))')])
    path = Path('tools/prepare_ab.py')
    source = path.read_text(encoding='utf-8')
    start, end = source.index('def prepare_runtime():'), source.index('\n\ndef main():')
    source = source[:start] + '''def prepare_runtime():
    from tools.runtime_install import ensure_runtime
    ensure_runtime(ROOT, read_token, clean_acquisition_environment, run_checked)
''' + source[end:]
    source = source.replace('ADCP_COMMIT = "b9c933bd7727b86149da891c323a27cde5afc956"',
                            'from suites.coding.adcp_loading import ADCP_COMMIT')
    path.write_text(source, encoding='utf-8', newline='\n')
    # Only the checked-in default is extended; release overlays never overwrite user AB.toml.
    path = Path('AB.toml')
    source = path.read_text(encoding='utf-8')
    source += '\n# Exact source admission; unchanged assets remain present in both arms.\nmax_file_bytes = 16777216\nmax_code_bytes = 16777216\n'
    path.write_text(source, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    apply()
