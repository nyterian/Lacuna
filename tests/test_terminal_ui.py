import io
import json
from pathlib import Path

from rich.console import Console
from lacuna import terminal_ui as ui
from lacuna.branches import topic_branch_request


def make_console():
    stream=io.StringIO();return Console(file=stream,width=120,color_system=None),stream


def test_numbered_menu_retries_bad_number(monkeypatch):
    console,output=make_console();values=iter(['bad','8','1'])
    monkeypatch.setattr('builtins.input',lambda:next(values))
    assert ui.choose(console,'Choose a task',[('1','Compare','Find related studies.'),('0','Back','Return.')])=='1'
    assert 'Find related studies.' in output.getvalue() and 'Choose one of the numbers' in output.getvalue()


def test_folder_is_remembered_and_invalid_settings_fall_back(tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'SETTINGS',tmp_path/'settings.json')
    console,_=make_console();folder=tmp_path/'folder with spaces'
    monkeypatch.setattr('builtins.input',lambda:'"'+str(folder)+'"')
    assert ui.change_folder(console,tmp_path)==folder
    assert ui.load_folder()==folder
    ui.SETTINGS.write_text('{bad JSON')
    assert ui.load_folder()==ui.ROOT/'data'/'packages'


def test_main_menu_descriptions_help_and_return(monkeypatch,tmp_path):
    import lacuna.cli as cli
    console,output=make_console();monkeypatch.setattr(cli,'console',console)
    monkeypatch.setattr(ui,'SETTINGS',tmp_path/'settings.json')
    values=iter(['6','','0']);monkeypatch.setattr('builtins.input',lambda:next(values))
    assert ui.run_workbench()==0
    text=output.getvalue()
    assert 'Compare research' in text and 'Map topic branches' in text and 'Command guide' in text
    assert 'python -m lacuna branches' in text and 'Lacuna.command' in text


def test_topic_flow_cancels_to_main_without_running(monkeypatch,tmp_path):
    import lacuna.cli as cli
    console,_=make_console();monkeypatch.setattr(cli,'console',console)
    monkeypatch.setattr(ui,'SETTINGS',tmp_path/'settings.json')
    values=iter(['3','online clustering','0','0']);monkeypatch.setattr('builtins.input',lambda:next(values))
    monkeypatch.setattr(cli,'execute',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('Unexpected execution')))
    assert ui.run_workbench()==0


def test_review_runs_then_opens_folder_and_returns_without_json(monkeypatch,tmp_path):
    import lacuna.cli as cli
    console,output=make_console();monkeypatch.setattr(cli,'console',console)
    values=iter(['1','1','2','0']);monkeypatch.setattr('builtins.input',lambda:next(values))
    calls=[];opened=[]
    def execute(request,**kwargs):
        calls.append(kwargs)
        return {'artifacts':{'assistant_document':str(tmp_path/'brief.assistant.md')}}
    monkeypatch.setattr(cli,'execute',execute);monkeypatch.setattr(ui,'open_folder',lambda path:opened.append(path))
    folder=ui.review_and_run(console,topic_branch_request('online clustering'),tmp_path,tmp_path)
    assert folder==tmp_path and opened==[tmp_path] and calls[0]['simple_ui'] is True
    requests=list((tmp_path/'technical'/'requests').glob('*.json'))
    assert len(requests)==1 and json.loads(requests[0].read_text())['config']['analysis_mode']=='topic_branches'
    assert 'Equivalent command' in output.getvalue() and 'ONE file' in output.getvalue()


def test_quick_comparison_needs_only_topic_scope_optional_keywords(monkeypatch):
    values=iter(['Online clustering','Compare memory and noise robustness.','prototype memory | streaming data'])
    monkeypatch.setattr('builtins.input',lambda:next(values))
    request=ui.quick_request()
    assert request.profile.title=='Online clustering'
    assert request.profile.concept_groups==[['prototype memory'],['streaming data']]


def test_corrupt_settings_type_does_not_crash(tmp_path,monkeypatch):
    monkeypatch.setattr(ui,'SETTINGS',tmp_path/'settings.json')
    ui.SETTINGS.write_text('[]')
    assert ui.load_folder()==ui.ROOT/'data'/'packages'
