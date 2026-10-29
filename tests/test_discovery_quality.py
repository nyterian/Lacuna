import io
import json
import zipfile
import httpx
from lacuna.models import ResearchProfile, RunConfig, Study
from lacuna.query import build_queries
from lacuna.sources import from_crossref, from_openalex, search_openalex, search_crossref
from lacuna.pipeline import apply_filters, run_research
from lacuna.scoring import deduplicate, rank_studies
from lacuna.selection import select_portfolio
from lacuna.export import build_package
from lacuna.net import WebClient


def profile(**updates):
    data=dict(title='Online prototype memory', description='Adaptive prototype memory with associative retrieval and hierarchical concept formation.', concept_groups=[['online learning'],['clustering']])
    data.update(updates)
    return ResearchProfile(**data)


def test_query_budget_preserves_architecture_and_named_comparators():
    p=profile(mechanism_groups=[['associative memory','content addressed memory']],seed_titles=['Distributed dual vigilance fuzzy ART'],targeted_queries=['"microcluster" AND "macrocluster"'])
    queries=build_queries(p,5)
    assert {q['family'] for q in queries}>={'broad','seed_title','targeted','mechanism'}
    assert any('associative memory' in q['boolean'] for q in queries)
    assert all(' OR ' not in q['plain'] for q in queries)


def test_description_generates_labeled_heuristic_queries():
    queries=build_queries(profile(),8)
    assert any(q['family']=='derived_phrase' for q in queries)
    assert any('prototype' in q['boolean'] or 'associative' in q['boolean'] for q in queries if q['family']=='derived_phrase')


def test_historical_default_and_explicit_lower_bound():
    old=Study(title='Foundational clustering',year=1991,type='conference-paper')
    assert apply_filters([old],profile())[0]==[old]
    assert apply_filters([old],profile(year_from=2000))[1][0]['reason']=='date'


def test_conference_and_preprint_types_normalized_and_retained():
    crossref=from_crossref({'title':['Density-based stream clustering'],'type':'proceedings-article','DOI':'10.1/demo'})
    legacy=from_openalex({'title':'Conference method','type':'proceedings-article'})
    modern=from_openalex({'title':'Conference method','type':'conference-paper'})
    preprint=from_crossref({'title':['New method'],'type':'posted-content'})
    assert {crossref.type,legacy.type,modern.type}=={'conference-paper'}
    assert preprint.type=='preprint'
    assert len(apply_filters([crossref,legacy,modern,preprint],profile())[0])==4


def test_historical_api_requests_omit_lower_date_and_openalex_type_filter(tmp_path):
    observed=[]
    def handler(request):
        observed.append(str(request.url))
        return httpx.Response(200,json={'meta':{},'results':[],'message':{'items':[]}})
    client=WebClient(tmp_path/'db',transport=httpx.MockTransport(handler))
    try:
        p=profile();cfg=RunConfig(max_queries=1)
        queries=build_queries(p,1)
        search_openalex(client,p,cfg,queries)
        search_crossref(client,p,cfg,queries)
        assert not any('from_publication_date' in u or 'from-pub-date' in u or 'type%3A' in u for u in observed)
    finally:client.close()


def test_portfolio_keeps_low_rank_architecture_and_historical_work():
    p=profile(mechanism_groups=[['associative memory']],seed_titles=['Named comparator'])
    studies=deduplicate([
        Study(title='Online learning clustering high score',abstract='online learning clustering',year=2025,type='review'),
        Study(title='Named comparator',abstract='online learning clustering',year=2020,type='conference-paper'),
        Study(title='Associative memory method',abstract='associative memory',year=2022,type='article'),
        Study(title='Historical online learning clustering',abstract='online learning clustering',year=1991,type='article')])
    studies=rank_studies(studies,p)
    selected,reasons=select_portfolio(studies,p,4)
    assert len(selected)==4
    assert any(any('named_comparator' in reason for reason in values) for values in reasons.values())
    assert any(s.year==1991 for s in selected)


def test_compact_catalogue_lists_omitted_records(tmp_path):
    records=[{'title':'Online learning clustering '+str(i),'abstract':'online learning clustering','type':'article'} for i in range(5)]
    result=run_research(profile(),RunConfig(sources=[],citation_rounds=0,max_downloads=0,compact_studies=2),imports=[('records.json',json.dumps(records).encode())],db_path=tmp_path/'db')
    with zipfile.ZipFile(io.BytesIO(build_package(result,compact=True))) as z:
        assert len(json.loads(z.read('studies.json')))==2
        catalogue=z.read('catalogue.csv').decode('utf-8-sig')
        assert all(s.id in catalogue for s in result.studies)
        assert len(json.loads(z.read('selection.json'))['reasons'])==2


def test_pdf_parsing_failures_are_counted_separately_from_http_errors(tmp_path):
    def handler(request):
        return httpx.Response(200,content=b'<html>not a PDF</html>')
    client=WebClient(tmp_path/'db',transport=httpx.MockTransport(handler))
    records=[{'title':'Online learning clustering','abstract':'online learning clustering','type':'article','pdf_url':'https://example.org/bad.pdf'}]
    try:
        result=run_research(profile(),RunConfig(sources=[],citation_rounds=0,max_downloads=1),imports=[('records.json',json.dumps(records).encode())],client=client)
        assert result.coverage['pdf_processing']['documents_failed']==1
        assert not result.coverage['source_errors']
        assert result.studies[0].full_text_attempts[0]['stage']=='parsing'
        assert any('parsing=1' in w for w in result.warnings)
    finally:client.close()


def test_alternate_oa_pdf_location_is_tried_after_parsing_failure(tmp_path):
    from test_research import pdf_bytes
    def handler(request):
        if request.url.host=='api.openalex.org':
            return httpx.Response(200,json={'meta':{},'results':[{'id':'https://openalex.org/W1','title':'Online learning clustering', 'type':'article',
                'locations':[{'is_oa':True,'pdf_url':'https://example.org/bad.pdf'},{'is_oa':True,'pdf_url':'https://example.org/good.pdf'}]}]})
        return httpx.Response(200,content=pdf_bytes() if request.url.path=='/good.pdf' else b'<html>not PDF</html>')
    client=WebClient(tmp_path/'db',transport=httpx.MockTransport(handler))
    try:
        result=run_research(profile(),RunConfig(sources=['openalex'],max_queries=1,citation_rounds=0,max_downloads=1),client=client)
        study=result.studies[0]
        assert study.pages_read==2 and study.full_text_status=='read'
        assert len(study.full_text_attempts)==2
        assert study.full_text_attempts[0]['stage']=='parsing'
        assert result.coverage['pdf_processing']['documents_failed']==0
    finally:client.close()
