import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from lacuna.models import ResearchProfile,RunConfig,RunResult,Study,Evidence,GapCandidate,GapEvidence
from lacuna.export import build_assistant_document,build_package,save_assistant_document

ROOT=Path(__file__).parents[1]


def sample_result():
    profile=ResearchProfile(title='Synthetic online clustering',description='Synthetic scope with ``` fenced source content.',concept_groups=[['online clustering']])
    studies=[Study(id='s_a',title='SYNTHETIC TEST SOURCE A',abstract='Exact source abstract.',url='https://example.org/a',year=2020,concept_matches=[['online clustering']],pages_read=2,pages_total=2,full_text_status='read',evidence=[Evidence(text='Exact source quotation on page two.',kind='full_text',page=2)]),
             Study(id='s_b',title='SYNTHETIC TEST SOURCE B',abstract='Unselected source abstract.',concept_matches=[[]])]
    return RunResult(run_id='single_doc_test',started_at='2026-10-29',profile=profile,config=RunConfig(compact_studies=1,package_studies=2),studies=studies,coverage={'limits':['Bounded search only.']},warnings=['Synthetic fixture only.'])


def test_brief_is_self_contained_with_sources_pages_and_selection():
    result=sample_result();body=build_assistant_document(result)
    for text in ['Instructions for your assistant','Exact source abstract.','Exact source quotation on page two.','"page": 2','https://example.org/a','s_a','s_b','Bounded search only.','Synthetic fixture only.','End of document']:
        assert text in body
    assert 'Unselected source abstract.' not in body
    assert 'Unselected source abstract.' in build_assistant_document(result,compact=False)
    assert 'evidence/s_a.md' not in body and 'research_profile.json' not in body
    assert '````json' in body  # embedded source fences cannot end their JSON section


def test_gap_brief_retains_author_quotes_and_current_status():
    result=sample_result();result.config.analysis_mode='field_gaps'
    evidence=GapEvidence(study_id='s_a',title='SYNTHETIC TEST THESIS',kind='full_text',page=2,quote='Future work should test recurring concepts.',cue='Future work',start=0,end=48)
    result.gap_candidates=[GapCandidate(id='g_test',category='future_work',statement=evidence.quote,evidence=[evidence])]
    body=build_assistant_document(result)
    assert evidence.quote in body and 'author_reported_unverified' in body and 'Gap extraction coverage' in body


def test_branch_brief_retains_all_paths_and_evidence():
    result=sample_result();result.config.analysis_mode='topic_branches';result.studies=[]
    result.topic_branches={'query':'Synthetic input','status':'ok','sampled_works':1,'placements':[{'topic_name':'Synthetic topic','basis':'sampled_publications_primary_topic','supporting_work_count':1,'path':[{'name':'Synthetic topic','kind':'topic','id':'https://openalex.org/T123'}],'siblings':[],'siblings_available':0,'supporting_works':[{'title':'SYNTHETIC supporting source','year':2020,'id':'https://openalex.org/W123'}]}]}
    body=build_assistant_document(result)
    assert 'Synthetic input' in body and 'https://openalex.org/T123' in body and 'SYNTHETIC supporting source' in body


def test_save_folder_creates_one_file_and_preserves_previous_export(tmp_path):
    folder=tmp_path/'new folder'/'briefs';result=sample_result()
    first=save_assistant_document(result,folder)
    first.write_text('Keep previous export',encoding='utf-8')
    second=save_assistant_document(result,folder)
    assert first!=second and first.read_text()=='Keep previous export'
    assert second.read_text(encoding='utf-8')==build_assistant_document(result)
    assert len(list(folder.iterdir()))==2
    with pytest.raises(OSError):save_assistant_document(result,first)


def test_archive_contains_same_single_attachment():
    result=sample_result()
    for compact in (True,False):
        with zipfile.ZipFile(io.BytesIO(build_package(result,compact))) as archive:
            assert archive.read('SEND_TO_ASSISTANT.md').decode()==build_assistant_document(result,compact)


def test_cli_places_primary_document_in_chosen_folder(tmp_path):
    folder=tmp_path/'chosen folder'
    run=subprocess.run([sys.executable,'-m','lacuna','run',str(ROOT/'examples/profile.json'),'--offline','--records',str(ROOT/'examples/synthetic_records.json'),'--quiet','--out',str(folder),'--db',str(tmp_path/'cache.sqlite')],capture_output=True,text=True,input='',timeout=30,cwd=ROOT)
    assert run.returncode==0,run.stdout+run.stderr
    summary=json.loads(run.stdout)
    primary=Path(summary['artifacts']['assistant_document'])
    assert primary.parent==folder and 'Instructions for your assistant' in primary.read_text(encoding='utf-8')
    assert Path(summary['artifacts']['package']).parent.parent.name=='technical'
    assert len(list(folder.glob('*.md')))==1 and not list(folder.glob('*.zip'))


def test_web_saves_single_brief_to_selected_folder(tmp_path):
    result=sample_result();app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    app.session_state['result']=result
    app.session_state['full_package']=build_package(result)
    app.session_state['compact_package']=build_package(result,True)
    app.run(timeout=30)
    next(t for t in app.text_input if t.label=='Save folder').set_value(str(tmp_path/'chosen'))
    next(b for b in app.button if b.label=='Save to folder').click().run()
    assert not app.exception
    assert len(list((tmp_path/'chosen').glob('*.assistant.md')))==1
    assert any('Assistant brief saved' in s.value for s in app.success)
