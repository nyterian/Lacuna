from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import httpx
from streamlit.testing.v1 import AppTest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from lacuna.models import Study, RunConfig
from lacuna.specification import field_gap_request
from lacuna.gaps import extract_field_gaps, verify_gap_candidates
from lacuna.scoring import deduplicate
from lacuna.net import WebClient
from lacuna.pipeline import run_research
from lacuna.export import build_package

ROOT=Path(__file__).parents[1]


def thesis(title='SYNTHETIC TEST THESIS: Online clustering',**kwargs):
    return Study(id='s_test',title=title,year=2020,type='dissertation',url='https://example.org/thesis',**kwargs)


def extract(studies,**limits):
    request=field_gap_request('online clustering',sources=[])
    cfg=RunConfig(analysis_mode='field_gaps',sources=[],gap_follow_up_queries=0,**limits)
    return extract_field_gaps(studies,request.profile,cfg)


def thesis_pdf():
    writer=PdfWriter();writer.add_metadata({'/Title':'SYNTHETIC TEST THESIS: Online clustering'})
    for text in ['Online clustering is examined in this synthetic thesis. Future work should investigate online clustering with recurring concepts and limited memory.',
                 'A limitation of this online clustering study is the small sample size. Further research should evaluate noise robustness in online clustering.']:
        page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 30 700 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output);return output.getvalue()


def test_exact_full_text_quote_page_and_offsets():
    pages=['Future Work\nFuture work should evaluate online clustering under recurring drift.',
           'Limitations\nA limitation of online clustering in this thesis is the restricted memory budget.']
    study=thesis(pages=pages,pages_read=2)
    gaps,coverage=extract([study])
    assert {g.category for g in gaps}=={'future_work','limitation'}
    assert coverage['theses_with_full_text']==1
    for gap in gaps:
        evidence=gap.evidence[0]
        assert pages[evidence.page-1][evidence.start:evidence.end]==evidence.quote
        assert evidence.kind=='full_text'
        assert gap.status=='author_reported_unverified'


def test_abstract_has_no_fabricated_page():
    gaps,_=extract([thesis(abstract='Future research should study online clustering with noisy data streams.')])
    assert len(gaps)==1
    assert gaps[0].evidence[0].page is None
    assert gaps[0].evidence[0].kind=='abstract'


def test_no_evidence_no_gap_and_non_thesis_excluded():
    plain=thesis(abstract='Online clustering is an incremental method for grouping observations.')
    article=thesis(title='Online clustering paper',abstract='Future work should improve online clustering.');article.type='article'
    unknown=thesis(title='Unknown document',abstract='Future work should improve online clustering.');unknown.type='unknown'
    gaps,coverage=extract([plain,article,unknown])
    assert not gaps
    assert coverage['theses_inspected']==1 and coverage['unknown_type_skipped']==1


def test_references_toc_and_negation_are_not_gap_claims():
    documents=[thesis(pages=['References\nFuture work on online clustering. A limitation of online clustering.'],pages_read=1),
               thesis(abstract='Online clustering has no limitations in this synthetic control.'),
               thesis(pages=['Contents\nFuture Work................ 42\nLimitations............... 50\nOnline clustering overview.......... 1'],pages_read=1)]
    assert extract(documents)[0]==[]


def test_topic_mismatch_is_skipped():
    gaps,coverage=extract([thesis(title='SYNTHETIC Marine geology',abstract='Future work should measure ocean sediment distribution.')])
    assert not gaps and coverage['topic_mismatch_skipped']==1


def test_duplicate_wording_groups_independent_theses_once():
    quote='Future work should evaluate online clustering with bounded memory.'
    studies=deduplicate([thesis(title='SYNTHETIC Online clustering A',abstract=quote),thesis(title='SYNTHETIC Online clustering B',abstract=quote)])
    gaps,_=extract(studies)
    assert len(gaps)==1 and gaps[0].support_count==2
    assert len({e.study_id for e in gaps[0].evidence})==2


def test_candidate_and_per_thesis_caps():
    text='Future work should test online clustering with noise. A limitation of online clustering is the fixed memory size. An open question concerns online clustering robustness.'
    assert len(extract([thesis(abstract=text)],gap_per_study=1)[0])==1
    assert len(extract([thesis(abstract=text)],gap_max_candidates=2)[0])==2


def test_related_work_does_not_close_gap(tmp_path):
    request=field_gap_request('online clustering')
    study=thesis(abstract='Future work should evaluate online clustering with recurring concepts.',doi='10.1234/own')
    gaps,_=extract([study])
    def handler(http_request):
        return httpx.Response(200,json={'meta':{},'results':[
            {'id':'https://openalex.org/W1','title':study.title,'type':'dissertation','publication_year':2020,'doi':'https://doi.org/10.1234/own'},
            {'id':'https://openalex.org/W2','title':'Online clustering with recurring concepts','type':'article','publication_year':2025,'doi':'https://doi.org/10.1234/new'},
            {'id':'https://openalex.org/W3','title':'Older related work','type':'article','publication_year':2018} ]})
    client=WebClient(tmp_path/'db',transport=httpx.MockTransport(handler))
    try:
        related,attempts=verify_gap_candidates(gaps,request.profile,request.config,client)
        assert len(related)==1 and related[0].year==2025
        assert gaps[0].status=='author_reported_unverified'
        assert gaps[0].verification_status=='related_work_found_review_required'
        assert attempts[0]['date_rule']=='same_or_later_publication_year'
        assert client.log[0]['purpose']=='gap_follow_up'
    finally:client.close()


def test_follow_up_failure_is_explicit(tmp_path):
    gaps,_=extract([thesis(abstract='Future work should improve online clustering with sparse data.')])
    client=WebClient(tmp_path/'db',transport=httpx.MockTransport(lambda r:httpx.Response(403)))
    try:
        related,attempts=verify_gap_candidates(gaps,field_gap_request('online clustering').profile,RunConfig(),client)
        assert not related and gaps[0].verification_status=='search_failed'
    finally:client.close()


def test_pdf_pipeline_user_assertion_and_export_roundtrip(tmp_path):
    request=field_gap_request('online clustering',sources=[])
    request.config=request.config.model_copy(update={'max_downloads':0,'gap_follow_up_queries':0,'local_documents_are_theses':True})
    result=run_research(request.profile,request.config,pdfs=[('synthetic-thesis.pdf',thesis_pdf())],db_path=tmp_path/'db')
    assert len(result.gap_candidates)>=2
    assert result.gap_candidates[0].evidence[0].source_type_basis=='user_asserted_thesis'
    assert result.gap_candidates[0].verification_status=='not_checked_no_supported_source'
    with zipfile.ZipFile(io.BytesIO(build_package(result,compact=True))) as archive:
        assert {'field_gaps.md','field_gaps.json','field_gaps.csv','gap_analysis.json','gap_related_studies.json'}<=set(archive.namelist())
        assert 'UNVERIFIED' in archive.read('field_gaps.md').decode()
    from lacuna.models import RunResult
    saved=RunResult.model_validate_json(result.model_dump_json())
    assert saved.gap_candidates[0].evidence[0].quote==result.gap_candidates[0].evidence[0].quote


def test_unknown_pdf_needs_user_assertion(tmp_path):
    request=field_gap_request('online clustering',sources=[])
    result=run_research(request.profile,request.config,pdfs=[('unknown.pdf',thesis_pdf())],db_path=tmp_path/'db')
    assert not result.gap_candidates
    assert result.gap_analysis['unknown_type_skipped']==1


def test_long_thesis_tail_sampling_preserves_physical_page():
    from lacuna.documents import read_pdf
    study=read_pdf(thesis_pdf(),'synthetic.pdf',max_pages=1,include_tail=True)
    study.type='dissertation';study.id='s_tail'
    gaps,coverage=extract([study])
    assert study.pages_total==2 and study.pages_read==1
    assert study.pages[0]=='' and study.full_text_status=='partial'
    assert gaps and all(e.page==2 for gap in gaps for e in gap.evidence)
    assert coverage['theses_partial_text']==1
    assert 'unread middle pages' in study.full_text_note


def test_topic_mode_queries_do_not_search_template_prose():
    from lacuna.gaps import build_gap_queries
    request=field_gap_request('online clustering')
    queries=build_gap_queries(request.profile,16)
    assert queries and all('online clustering' in q['boolean'] for q in queries)
    assert not any(q['family']=='derived_phrase' for q in queries)


def test_pdf_wrapped_cue_and_new_chapter_after_references():
    study=thesis(pages=['References\nA bibliography entry about online clustering.',
                        'CHAPTER 2\nMethods\nThis chapter considers online clustering.',
                        'Conclusions and future work\nFuture\nwork should evaluate online clustering in noisy environments.'],pages_read=3)
    gaps,_=extract([study])
    assert gaps and gaps[0].evidence[0].page==3
    assert 'Future\nwork' in gaps[0].statement


def test_completed_further_evaluation_is_not_future_work():
    assert not extract([thesis(abstract='Further evaluation confirmed that online clustering performed well in this synthetic test.')])[0]


def test_long_source_excerpt_is_marked_and_remains_exact():
    text='Future work should investigate online clustering '+('under different data conditions '*70)
    study=thesis(abstract=text)
    gaps,_=extract([study])
    evidence=gaps[0].evidence[0]
    assert evidence.truncated and len(evidence.quote)<=1400
    assert text[evidence.start:evidence.end]==evidence.quote


def test_cli_topic_only_mode_with_offline_records(tmp_path):
    records=tmp_path/'theses.json'
    records.write_text(json.dumps([{'title':'SYNTHETIC Online clustering thesis','type':'dissertation','year':2020,'abstract':'Future work should evaluate online clustering on recurring data.'}]))
    run=subprocess.run([sys.executable,'-m','lacuna','gaps','online clustering','--offline','--records',str(records),'--quiet','--out',str(tmp_path/'out'),'--db',str(tmp_path/'db')],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr
    payload=json.loads(run.stdout)
    assert len(payload['gap_candidates'])==1
    assert Path(payload['artifacts']['field_gaps_report']).exists()


def test_web_topic_form_rejects_empty_input():
    app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
    next(button for button in app.button if button.label=='Find field gaps').click().run()
    assert app.error and not app.exception


def test_web_renders_saved_gap_evidence(tmp_path):
    request=field_gap_request('online clustering',sources=[])
    records=[{'title':'SYNTHETIC Online clustering thesis','type':'dissertation','year':2020,'url':'https://example.org/thesis','abstract':'Future work should evaluate online clustering under drift.'}]
    result=run_research(request.profile,request.config,imports=[('records.json',json.dumps(records).encode())],db_path=tmp_path/'db')
    app=AppTest.from_file(str(ROOT/'app.py'))
    app.session_state['result']=result
    app.session_state['full_package']=build_package(result)
    app.session_state['compact_package']=build_package(result,compact=True)
    app.run(timeout=30)
    assert not app.exception
    assert any(box.label=='gap.id' for box in app.selectbox)


def test_plural_future_works_and_overview_reference():
    from lacuna.gaps import excerpt_spans
    assert list(excerpt_spans("Future works should evaluate online clustering on larger datasets."))
    assert not list(excerpt_spans("Chapter 5 presents conclusions and future works."))
