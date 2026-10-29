import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest
from rich.console import Console
from streamlit.testing.v1 import AppTest

from lacuna.branches import topic_branch_request, branch_tree, branch_svg, branch_report, rich_tree, tree_lines
from lacuna.pipeline import run_research
from lacuna.net import WebClient
from lacuna.export import build_package
from lacuna.models import RunResult

ROOT=Path(__file__).parents[1]


def topic(ident='T123',name='SYNTHETIC Online clustering'):
    return {'id':'https://openalex.org/'+ident,'display_name':name,
            'domain':{'id':'https://openalex.org/domains/3','display_name':'Physical Sciences'},
            'field':{'id':'https://openalex.org/fields/17','display_name':'Computer Science'},
            'subfield':{'id':'https://openalex.org/subfields/1702','display_name':'Artificial Intelligence'}}


def run_fixture(tmp_path,handler=None):
    def response(request):
        if request.url.path=='/works':
            works=[{'id':f'https://openalex.org/W{i}','display_name':f'SYNTHETIC publication {i}','publication_year':2020,'primary_topic':topic()} for i in range(3)]
            works.append({'id':'https://openalex.org/W5','display_name':'SYNTHETIC alternate placement','primary_topic':topic('T456','SYNTHETIC Data analysis')})
            return httpx.Response(200,json={'meta':{'count':100},'results':works})
        ident=request.url.path.rsplit('/',1)[-1]
        item=topic(ident,'SYNTHETIC Online clustering' if ident=='T123' else 'SYNTHETIC Data analysis')
        item['siblings']=[{'id':'https://openalex.org/T789','display_name':'SYNTHETIC Neighbor'},{'id':'https://openalex.org/T789','display_name':'Duplicate'}]
        return httpx.Response(200,json=item)
    client=WebClient(tmp_path/'test.sqlite',transport=httpx.MockTransport(handler or response))
    req=topic_branch_request('Online clustering with prototype memory')
    try:return run_research(req.profile,req.config,client=client)
    finally:client.close()


def test_source_backed_paths_counts_and_peer_relationship(tmp_path):
    result=run_fixture(tmp_path);data=result.topic_branches
    assert data['status']=='ok' and data['sampled_works']==4
    assert len(data['placements'])==2
    placement=data['placements'][0]
    assert placement['supporting_work_count']==3 and len(placement['supporting_works'])==3
    assert [n['kind'] for n in placement['path']]==['domain','field','subfield','topic']
    assert len(placement['siblings'])==1
    tree=branch_tree(data)
    subfield=tree['children'][0]['children'][0]['children'][0]
    assert [n['kind'] for n in subfield['children']]==['topic','peer']
    assert subfield['children'][0]['children'][0]['kind']=='query'
    assert all(n['kind']!='peer' for n in subfield['children'][0]['children'])
    assert len(result.search_log)==3 and result.coverage['http_requests']==3


def test_terminal_and_svg_share_labels_and_source_roundtrip(tmp_path):
    result=run_fixture(tmp_path);data=result.topic_branches
    svg=branch_svg(data);ElementTree.fromstring(svg)
    assert 'stroke-dasharray' in svg and data['query'] in svg
    text=tree_lines(branch_tree(data))
    output=io.StringIO();Console(file=output,width=150,color_system=None).print(rich_tree(data))
    for label in ['Physical Sciences','Computer Science','SYNTHETIC Neighbor',data['query']]:
        assert label in svg and label in text and label in output.getvalue()
    assert RunResult.model_validate_json(result.model_dump_json()).topic_branches==data
    for compact in (False,True):
        with zipfile.ZipFile(io.BytesIO(build_package(result,compact=compact))) as archive:
            assert {'topic_branches.json','topic_branches.svg','topic_branches.txt','topic_branches.md'}<=set(archive.namelist())
            assert json.loads(archive.read('topic_branches.json'))==data
            assert b'probabilities' in archive.read('ASSISTANT_PROMPT.md')


def test_no_matches_does_not_invent_tree(tmp_path):
    result=run_fixture(tmp_path,lambda r:httpx.Response(200,json={'results':[]}))
    assert result.topic_branches['status']=='no_matches'
    assert not result.topic_branches['placements']
    assert 'No source-backed placement' in tree_lines(branch_tree(result.topic_branches))


def test_fallback_taxonomy_without_publications(tmp_path):
    def response(r):
        if r.url.path=='/works':return httpx.Response(200,json={'results':[]})
        if r.url.path=='/topics':return httpx.Response(200,json={'results':[topic()]})
        return httpx.Response(200,json=topic())
    data=run_fixture(tmp_path,response).topic_branches
    assert data['placements'][0]['basis']=='direct_taxonomy_search'
    assert data['placements'][0]['supporting_work_count']==0


def test_failed_detail_retains_known_path_and_no_fake_peers(tmp_path):
    def response(r):
        if r.url.path=='/works':return httpx.Response(200,json={'results':[{'primary_topic':topic()}]})
        return httpx.Response(403)
    data=run_fixture(tmp_path,response).topic_branches
    assert data['status']=='partial' and data['errors']
    assert data['placements'][0]['hierarchy_complete']
    assert data['placements'][0]['siblings_available'] is None
    assert data['placements'][0]['siblings']==[]


def test_budget_failure_is_visible_and_key_is_redacted(tmp_path):
    client=WebClient(tmp_path/'budget.sqlite',budget=1,transport=httpx.MockTransport(lambda r:httpx.Response(401)))
    req=topic_branch_request('Online clustering')
    try:result=run_research(req.profile,req.config,client=client,openalex_key='secret-key')
    finally:client.close()
    assert result.topic_branches['status']=='failed'
    assert 'secret-key' not in result.model_dump_json()


def test_unsafe_source_labels_are_escaped_in_svg_and_rich(tmp_path):
    result=run_fixture(tmp_path)
    result.topic_branches['query']='<script>alert(1)</script> [bold]query[/bold]'
    svg=branch_svg(result.topic_branches)
    assert '<script>' not in svg and '&lt;script&gt;' in svg
    ElementTree.fromstring(svg)
    output=io.StringIO();Console(file=output,color_system=None,width=150).print(rich_tree(result.topic_branches))
    assert '[bold]query[/bold]' in output.getvalue()


def test_shared_request_and_offline_mode_validation(tmp_path):
    from lacuna.models import RunConfig
    from lacuna.specification import parse_request
    request=topic_branch_request('Online clustering')
    assert parse_request(request.model_dump_json()).config.analysis_mode=='topic_branches'
    request.config.sources=[]
    with pytest.raises(ValueError,match='requires the OpenAlex'):run_research(request.profile,request.config,db_path=tmp_path/'offline.sqlite')
    with pytest.raises(ValueError):RunConfig(branch_max_matches=6)


def test_web_empty_topic_error_and_saved_tree(tmp_path):
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    next(b for b in app.button if b.label=='Map topic branches').click().run()
    assert app.error and not app.exception
    result=run_fixture(tmp_path)
    app.session_state['result']=result
    app.session_state['full_package']=build_package(result)
    app.session_state['compact_package']=build_package(result,compact=True)
    app.run(timeout=30)
    assert not app.exception
    assert any(s.label=='Suggested taxonomy placement' for s in app.selectbox)
    assert any('stroke-dasharray' in m.value for m in app.markdown)


def test_cli_keeps_json_stdout_and_draws_tree_on_stderr(tmp_path, monkeypatch, capsys):
    import lacuna.cli as cli
    result=run_fixture(tmp_path)
    monkeypatch.setattr(cli,'run_research',lambda *args,**kwargs:result)
    code=cli.main(['branches','Online clustering','--out',str(tmp_path/'out'),'--db',str(tmp_path/'cli.sqlite')])
    output=capsys.readouterr()
    assert code in (None,0)
    summary=json.loads(output.out)
    assert summary['topic_branches']['placements'][0]['supporting_work_count']==3
    assert 'Physical Sciences' in output.err and '[suggested' in output.err and 'placement]' in output.err
    assert Path(summary['artifacts']['topic_branches_svg']).exists()


def test_alternative_tree_and_incomplete_parents(tmp_path):
    data=run_fixture(tmp_path).topic_branches
    assert 'SYNTHETIC Data analysis' in tree_lines(branch_tree(data,1))
    data['placements'][0]['path']=[data['placements'][0]['path'][-1]]
    text=tree_lines(branch_tree(data))
    assert 'Physical Sciences' not in text and '[neighbor]' not in text


def test_compact_svg_preserves_tree_and_wraps_labels(tmp_path):
    data=run_fixture(tmp_path).topic_branches
    svg=branch_svg(data,width=360)
    ElementTree.fromstring(svg)
    assert 'width="360"' in svg and 'Physical Sciences' in svg
    assert data['query'] in svg  # accessible description retains full query
