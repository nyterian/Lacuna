from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from lacuna.cli import main, guided_request, read_pasted_json
from lacuna.specification import example_request, parse_request, input_prompt, request_template
from lacuna.models import ResearchRequest

ROOT = Path(__file__).parents[1]


def invoke(*arguments, stdin=None):
    return subprocess.run([sys.executable, '-m', 'lacuna', *map(str, arguments)], input=stdin, text=True, cwd=ROOT, capture_output=True, timeout=30)


def test_template_schema_and_prompt_are_portable_json():
    template = invoke('template')
    assert template.returncode == 0 and json.loads(template.stdout) == request_template()
    schema = json.loads(invoke('template', '--schema').stdout)
    assert schema['additionalProperties'] is False
    assert 'concept_groups' in schema['$defs']['ResearchProfile']['properties']
    assert 'Field specific lacuna identifier' in input_prompt()
    assert 'shell commands' in input_prompt()


def test_validate_stdin_and_markdown_fences():
    request = example_request()
    run = invoke('validate', '-', stdin='```json\n' + json.dumps(request) + '\n```')
    assert run.returncode == 0
    assert json.loads(run.stdout)['profile'] == request['profile']
    assert not run.stderr


def test_strict_schema_rejects_hallucinated_credentials():
    request = example_request()
    request['config']['api_key'] = 'NOT_A_REAL_SECRET'
    run = invoke('validate', '-', stdin=json.dumps(request))
    assert run.returncode == 2
    payload = json.loads(run.stdout)
    assert payload['status'] == 'error'
    assert payload['error'][0]['field'] == 'config.api_key'
    assert 'NOT_A_REAL_SECRET' not in run.stdout


def test_invalid_json_returns_machine_readable_error():
    run = invoke('validate', '-', stdin='{bad JSON}')
    assert run.returncode == 2
    assert json.loads(run.stdout)['status'] == 'error'


def test_paste_accepts_multiline_json_without_end(monkeypatch):
    lines = iter(json.dumps(example_request(), indent=2).splitlines())
    monkeypatch.setattr('builtins.input', lambda: next(lines))
    request = read_pasted_json()
    assert request.profile.title.startswith('Generative AI')


def test_guided_wizard_collects_fields(monkeypatch):
    values = iter([
        'Critical thinking and generative AI',
        'Compare empirical evidence about generative AI and critical thinking.',
        'generative AI | large language model', 'critical thinking', '',
        '', '', '', '', '', '', '',
        '', '', '',
        '', '', '',
        'none',
        '', '', '',
        '', str(ROOT/'examples/synthetic_records.json'),
    ])
    monkeypatch.setattr('builtins.input', lambda: next(values))
    request = guided_request()
    assert len(request.profile.concept_groups) == 2
    assert request.config.sources == []
    assert request.inputs.records


def test_offline_cli_outputs_json_and_replayable_request(tmp_path):
    request = example_request()
    request['config'].update(sources=[], citation_rounds=0, max_downloads=0)
    source = tmp_path/'inputs'
    source.mkdir()
    source.joinpath('records.json').write_bytes((ROOT/'examples/synthetic_records.json').read_bytes())
    request['inputs']['records'] = ['records.json']
    spec = source/'request.json'
    spec.write_text(json.dumps(request))
    out = tmp_path/'output'
    run = invoke('run', spec, '--quiet', '--out', out, '--db', tmp_path/'cache.db')
    assert run.returncode == 0, run.stdout + run.stderr
    summary = json.loads(run.stdout)
    assert summary['studies'] == 3
    assert not run.stderr
    normalized = json.loads(Path(summary['artifacts']['request_json']).read_text())
    assert Path(normalized['inputs']['records'][0]).is_absolute()
    assert Path(normalized['inputs']['records'][0]).exists()
    full_result = json.loads(Path(summary['artifacts']['result_json']).read_text())
    assert len(full_result['studies']) == 3
    with zipfile.ZipFile(summary['artifacts']['package']) as z:
        assert z.testzip() is None
        assert json.loads(z.read('request.json'))['inputs'] == {'pdfs': [], 'records': []}
        assert 'Field specific lacuna identifier' in z.read('README.md').decode()
        assert 'Interpret this research package' in z.read('ASSISTANT_PROMPT.md').decode()


def test_init_never_silently_overwrites(tmp_path):
    first = invoke('init', '--dir', tmp_path)
    assert first.returncode == 0
    assert len(json.loads(first.stdout)['files']) == 4
    second = invoke('init', '--dir', tmp_path)
    assert second.returncode == 2
    assert 'already exist' in json.loads(second.stdout)['error']


def test_paste_command_piped_input_keeps_stdout_json():
    run = invoke('paste', stdin=json.dumps(example_request()) + '\n')
    assert run.returncode == 0
    assert json.loads(run.stdout)['schema_version'] == '1.0'


def test_noninteractive_no_args_prints_help_without_hanging():
    run = invoke()
    assert run.returncode == 0 and 'usage: lacuna' in run.stdout


def test_cli_file_flags_are_recorded_for_replay(tmp_path):
    run = invoke('run', ROOT/'examples/profile.json', '--offline', '--records', ROOT/'examples/synthetic_records.json',
                 '--quiet', '--out', tmp_path/'out', '--db', tmp_path/'cache.db')
    assert run.returncode == 0
    summary = json.loads(run.stdout)
    request = json.loads(Path(summary['artifacts']['request_json']).read_text())
    assert request['inputs']['records'] == [str((ROOT/'examples/synthetic_records.json').resolve())]
    assert request['config']['sources'] == []
