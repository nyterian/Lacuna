from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from lacuna import APP_NAME, __version__
from lacuna.models import ResearchRequest, ResearchProfile, RunConfig, RunResult
from lacuna.pipeline import run_research
from lacuna.branches import topic_branch_request, branch_svg, branch_tree, tree_lines, branch_report
from lacuna.export import build_package, ASSISTANT_PROMPT
from lacuna.specification import request_template, example_request, input_prompt, parse_request, field_gap_request

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "research.sqlite"

st.set_page_config(page_title=APP_NAME, page_icon="⌕", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
:root {color-scheme:dark;}
.stApp,h1,h2,h3,h4,h5,h6,p,li,label,button,input,textarea,[role="tab"],[role="option"],[data-baseweb="select"] {font-family:"Times New Roman",Times,serif !important;}
pre,code,pre *,[data-testid="stCode"] *, .st-key-json_request textarea {font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace !important;}
.block-container {max-width:1280px;padding-top:1.65rem;padding-bottom:3rem;}
h1 {font-size:1.22rem !important;font-weight:600 !important;line-height:1.45 !important;letter-spacing:-.02em !important;margin-bottom:.1rem !important;}
h2 {font-size:1.05rem !important;font-weight:600 !important;line-height:1.45 !important;margin-top:1.2rem !important;}
h3 {font-size:.92rem !important;font-weight:600 !important;line-height:1.45 !important;}
p,li,label {font-size:.84rem !important;}
[data-testid="stCaptionContainer"] p {font-size:.73rem !important;color:#A3ADBA;}
[data-testid="stCaptionContainer"] {opacity:1 !important;color:#A3ADBA !important;}
[data-testid="stSidebar"] {border-right:1px solid #242B35;}
[data-testid="stSidebar"] .block-container {padding-top:1.6rem;}
[data-testid="stForm"] {border:0;padding:0;}
input,textarea {caret-color:#B4DFC4;font-size:.82rem !important;}
::selection {background:#294638;color:#F0F5F3;}
a {text-underline-offset:3px;}
button:focus-visible,a:focus-visible,input:focus-visible,textarea:focus-visible {outline:2px solid #B4DFC4;outline-offset:3px;}
button[kind^="primary"],button[kind^="primary"] p,button[kind^="primary"] span {color:#080A0D !important;}
[data-testid="stDataFrame"] {font-variant-numeric:tabular-nums;}
.branch-map-mobile {display:none;}
@media(max-width:640px) {.branch-map-desktop {display:none;}.branch-map-mobile {display:block;}}
* {scrollbar-color:#39424F #080A0D;scrollbar-width:thin;}
@media(max-width:640px) {.block-container {padding:1rem .85rem 2rem;}h1{font-size:1.04rem !important;}}
@media(prefers-reduced-motion:reduce) {* {animation:none !important;transition:none !important;}}
</style>""", unsafe_allow_html=True)


def terms(value):
    return [part.strip() for part in value.replace("\n", "|").split("|") if part.strip()]


def errors(exc):
    if isinstance(exc, ValidationError):
        for item in exc.errors():
            field = ".".join(map(str, item["loc"])) or "request"
            st.error(f"{field}: {item['msg']}")
    elif isinstance(exc, json.JSONDecodeError):
        st.error(f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    else:
        st.error(str(exc))


def activate_result(result):
    st.session_state.result = result
    st.session_state.full_package = build_package(result)
    st.session_state.compact_package = build_package(result, compact=True)


def run_request(request, pdf_files, record_files, oa_key, core_key):
    if request.inputs.pdfs or request.inputs.records:
        raise ValueError("inputs paths are CLI-only. Clear them and upload the files in local_inputs for web use.")
    if not request.config.sources and not pdf_files and not record_files:
        raise ValueError("Select a source or upload local PDF/CSV/JSON files.")
    if "core" in request.config.sources and not core_key:
        raise ValueError("CORE requires CORE_API_KEY. Configure it in Runtime or remove core from config.sources.")
    if "oai" in request.config.sources and not request.config.oai_url:
        raise ValueError("config.oai_url is required for the oai source.")
    progress = st.progress(0, text="Initializing discovery")
    with st.spinner("Collecting records and extracting evidence..."):
        result = run_research(request.profile, request.config,
                              pdfs=[(f.name, f.getvalue()) for f in pdf_files],
                              imports=[(f.name, f.getvalue()) for f in record_files], db_path=DB,
                              openalex_key=oa_key, core_key=core_key,
                              progress=lambda value, message: progress.progress(value, text=message))
    activate_result(result)
    if result.config.analysis_mode == "topic_branches":
        st.success(f"Topic map ready / {len(result.topic_branches.get('placements', []))} suggested placements / inspect Topic branches or download Artifacts")
    else:
        st.success(f"run_id={result.run_id} / records={len(result.studies)} / inspect Results or download Artifacts")
    for warning in result.warnings:
        st.warning(warning)


if "draft" not in st.session_state:
    st.session_state.draft = request_template()
if "json_request" not in st.session_state:
    st.session_state.json_request = json.dumps(st.session_state.draft, indent=2)

with st.sidebar:
    st.subheader("Runtime")
    st.caption(f"localhost / v{__version__} / MIT")
    st.code("python -m lacuna\npython -m lacuna web", language="bash")
    if st.button("Load example specification", width="stretch"):
        st.session_state.draft = example_request()
        st.session_state.json_request = json.dumps(example_request(), indent=2)
        st.session_state.form_version = st.session_state.get("form_version", 0) + 1
        st.rerun()
    with st.expander("Source credentials"):
        st.caption("Runtime-only. Never included in request JSON or exported packages.")
        oa_key = st.text_input("OPENALEX_API_KEY", type="password", value=os.getenv("OPENALEX_API_KEY", ""))
        core_key = st.text_input("CORE_API_KEY", type="password", value=os.getenv("CORE_API_KEY", ""))
    st.divider()
    st.caption("Shared request contract")
    st.code("lacuna template --prompt\nlacuna validate request.json\nlacuna run request.json", language="bash")
    st.caption("Word + character TF-IDF. Scores are uncalibrated proximity, not novelty probabilities. No LLM calls.")

st.title(APP_NAME)
st.caption("Research specification → bounded retrieval → proximity ranking → inspectable evidence → portable artifacts")
spec_tab, results_tab, gaps_tab, branches_tab, artifacts_tab, runs_tab = st.tabs(["Specification", "Results", "Field gaps", "Topic branches", "Artifacts", "Runs"])

with spec_tab:
    mode = st.radio("input_mode", ["Form", "JSON"], horizontal=True, label_visibility="collapsed")
    a, b, c = st.columns(3)
    a.download_button("template.json", json.dumps(request_template(), indent=2), "request.template.json", "application/json", width="stretch")
    b.download_button("input.prompt", input_prompt(), "INPUT_PROMPT.md", "text/markdown", width="stretch")
    c.download_button("schema.json", json.dumps(ResearchRequest.model_json_schema(), indent=2), "request.schema.json", "application/json", width="stretch")
    st.caption("Send INPUT_PROMPT.md to your assistant, then paste its request JSON. Both interfaces use the same schema.")
    with st.expander("local_inputs / optional file uploads"):
        a, b = st.columns(2)
        pdf_files = a.file_uploader("pdfs", type=["pdf"], accept_multiple_files=True)
        record_files = b.file_uploader("records", type=["csv", "json"], accept_multiple_files=True)
        st.caption("CSV/JSON fields: title, abstract, year, authors, doi, type, url, language, pdf_url. Web requests use uploads; local filesystem paths are CLI-only.")
        st.download_button("records_template.csv", (ROOT / "examples/records_template.csv").read_bytes(), "records_template.csv", "text/csv")
    if mode == "JSON":
        uploaded_spec = st.file_uploader("Load a request JSON file", type=["json"], key="request_upload")
        if uploaded_spec is not None:
            signature = uploaded_spec.name + str(hash(uploaded_spec.getvalue()))
            if st.session_state.get("loaded_spec_signature") != signature:
                st.session_state.json_request = uploaded_spec.getvalue().decode("utf-8-sig")
                st.session_state.loaded_spec_signature = signature
        source = st.text_area("request.json", key="json_request", height=580, help="Strict JSON. Unknown fields are rejected. Credentials belong in environment variables or Runtime.")
        a, b, c = st.columns(3)
        validate_clicked = a.button("Validate specification", width="stretch")
        run_clicked = b.button("Run discovery", type="primary", width="stretch", key="json_run")
        c.download_button("Save request JSON", source, "request.json", "application/json", width="stretch")
        if validate_clicked or run_clicked:
            try:
                request = parse_request(source)
                if validate_clicked:
                    st.success(f"Valid schema_version={request.schema_version} / concept_groups={len(request.profile.concept_groups)} / sources={','.join(request.config.sources) or 'offline'}")
                    st.json(request.model_dump(), expanded=False)
                else:
                    run_request(request, pdf_files, record_files, oa_key, core_key)
            except (ValidationError, ValueError, OSError) as exc:
                errors(exc)
    else:
        draft = st.session_state.draft
        p, cfg = draft["profile"], draft["config"]
        with st.form(f"specification_{st.session_state.get('form_version', 0)}"):
            title = st.text_input("profile.title *", value=p["title"], max_chars=500, placeholder="Working research title")
            description = st.text_area("profile.description *", value=p["description"], height=85, placeholder="Research scope, constructs, and context")
            groups = st.text_area("profile.concept_groups *", value="\n".join(" | ".join(g) for g in p["concept_groups"]), height=95,
                                  placeholder="generative AI | large language model\ncritical thinking | critical reasoning",
                                  help="One concept per line. Separate synonyms with |. Different lines are distinct concepts.")
            mechanisms = st.text_area("profile.mechanism_groups", value="\n".join(" | ".join(g) for g in p.get("mechanism_groups",[])), height=85, help="One architectural mechanism per line; synonyms separated by |.")
            comparator_titles = st.text_area("profile.seed_titles", value="\n".join(p.get("seed_titles",[])), height=70, help="One known comparator method or paper title per line.")
            targeted = st.text_area("profile.targeted_queries", value="\n".join(p.get("targeted_queries",[])), height=70, help="Optional explicit Boolean searches, one per line.")
            a, b = st.columns(2)
            with a:
                questions = st.text_area("profile.questions", value="\n".join(p["questions"]), height=70)
                population = st.text_input("profile.population", value=" | ".join(p["population"]))
                methods = st.text_input("profile.methods", value=" | ".join(p["methods"]))
                geography = st.text_input("profile.geography", value=" | ".join(p["geography"]))
            with b:
                historical = st.checkbox("No lower year bound / include historical prior work", value=p["year_from"] is None)
                years = st.columns(2)
                lower_year = years[0].number_input("year_from", 1500, 2100, p["year_from"] or 1900, disabled=historical)
                year_from = None if historical else lower_year
                year_to = years[1].number_input("year_to", 1500, 2100, p["year_to"])
                types = st.multiselect("profile.types *", ["article", "conference-paper", "preprint", "review", "dissertation", "other"], default=p["types"])
                languages = st.text_input("profile.languages", value=" | ".join(p["languages"]), placeholder="en | de (empty = all)")
                excluded_terms = st.text_input("profile.excluded_terms", value=" | ".join(p["excluded_terms"]))
            seed_dois = st.text_area("profile.seed_dois", value="\n".join(p["seed_dois"]), height=70, help="One DOI or doi.org URL per line.")
            sources = st.multiselect("config.sources", ["openalex", "crossref", "core", "oai"], default=cfg["sources"])
            st.caption("No sources = local input only. CORE requires a key. OAI harvests bounded repository records. YOK supports local record/PDF import; no automatic bulk YOK crawl.")
            with st.expander("config / retrieval, evidence, and export limits"):
                a, b, c = st.columns(3)
                per_source = a.number_input("per_source", 1, 2000, cfg["per_source"])
                max_queries = b.number_input("max_queries", 1, 60, cfg["max_queries"])
                budget = c.number_input("request_budget", 1, 500, cfg["request_budget"])
                a, b, c = st.columns(3)
                rounds = a.number_input("citation_rounds", 0, 2, cfg["citation_rounds"])
                seeds = b.number_input("citation_seeds", 1, 10, cfg["citation_seeds"])
                downloads = c.number_input("max_downloads", 0, 50, cfg["max_downloads"])
                a, b, c = st.columns(3)
                max_mb = a.number_input("max_pdf_mb", 1, 100, cfg["max_pdf_mb"])
                max_pages = b.number_input("max_pages", 1, 1500, cfg["max_pages"])
                evidence_count = c.number_input("evidence_per_study", 1, 20, cfg["evidence_per_study"])
                a, b = st.columns(2)
                package_count = a.number_input("package_studies", 1, 200, cfg["package_studies"])
                compact_count = b.number_input("compact_studies", 1, 50, cfg["compact_studies"])
                oai_url = st.text_input("oai_url", value=cfg["oai_url"])
                oai_set = st.text_input("oai_set", value=cfg["oai_set"])
                use_cache = st.checkbox("use_cache / 24-hour local response cache", value=cfg["use_cache"])
            a, b = st.columns(2)
            prepare = a.form_submit_button("Build request JSON", width="stretch")
            submit = b.form_submit_button("Run discovery", type="primary", width="stretch")
        if prepare or submit:
            try:
                profile = ResearchProfile(mechanism_groups=[terms(line) for line in mechanisms.splitlines() if line.strip()], seed_titles=[t.strip() for t in comparator_titles.splitlines() if t.strip()], targeted_queries=[t.strip() for t in targeted.splitlines() if t.strip()], title=title, description=description, concept_groups=[terms(line) for line in groups.splitlines() if line.strip()],
                                          questions=[q.strip() for q in questions.splitlines() if q.strip()], population=terms(population), methods=terms(methods),
                                          geography=terms(geography), excluded_terms=terms(excluded_terms), seed_dois=[s.strip() for s in seed_dois.splitlines() if s.strip()],
                                          year_from=year_from, year_to=year_to, types=types, languages=terms(languages))
                config = RunConfig(sources=sources, per_source=per_source, max_queries=max_queries, request_budget=budget,
                                   citation_rounds=rounds, citation_seeds=seeds, max_downloads=downloads, max_pdf_mb=max_mb, max_pages=max_pages,
                                   evidence_per_study=evidence_count, package_studies=package_count, compact_studies=compact_count,
                                   oai_url=oai_url, oai_set=oai_set, use_cache=use_cache)
                request = ResearchRequest(profile=profile, config=config)
                st.session_state.prepared_request = request.model_dump_json(indent=2)
                st.session_state.draft = request.model_dump()
                if submit:
                    run_request(request, pdf_files, record_files, oa_key, core_key)
            except (ValidationError, ValueError, OSError) as exc:
                errors(exc)
        if st.session_state.get("prepared_request"):
            with st.expander("request.json / generated from form", expanded=bool(prepare)):
                text = st.session_state.prepared_request
                st.code(text, language="json")
                st.download_button("Save generated request", text, "request.json", "application/json")

with gaps_tab:
    st.subheader("Open questions reported in theses")
    st.write("Enter a field or topic. Extract limitations, future-work proposals, and explicitly unresolved questions from accessible thesis text.")
    st.caption("Author-reported statements are candidates, not verified present-day gaps. Later studies may have addressed them. No LLM is called.")
    with st.form("field_gaps_form"):
        gap_topic=st.text_input("Research field / topic",placeholder="e.g. online clustering")
        gap_terms=st.text_area("Keyword groups (optional)",height=75,placeholder="One concept per line; synonyms separated by |. Leave blank to use the topic.")
        a,b=st.columns(2)
        gap_sources=a.multiselect("Thesis sources",["openalex","crossref","core","oai"],default=["openalex","crossref"])
        gap_local=b.checkbox("Offline / local files only",value=False)
        gap_pdfs=st.file_uploader("Upload thesis PDFs",type=["pdf"],accept_multiple_files=True,key="gap_pdfs")
        gap_records=st.file_uploader("Upload thesis records (CSV / JSON)",type=["csv","json"],accept_multiple_files=True,key="gap_records")
        gap_attested=st.checkbox("I identify the uploaded PDFs as theses",value=False,help="PDF files do not reliably identify their publication type. Without this assertion, unknown-type PDFs are not used for thesis-only gap extraction.")
        with st.expander("Gap extraction and retrieval limits"):
            a,b,c=st.columns(3)
            gap_cap=a.number_input("gap_max_candidates",1,100,40)
            gap_per=b.number_input("gap_per_study",1,20,6)
            gap_follow=c.number_input("gap_follow_up_queries",0,10,3)
            a,b,c=st.columns(3)
            gap_downloads=a.number_input("Thesis PDF download limit",0,50,8)
            gap_source_cap=b.number_input("Thesis records per source",1,2000,100)
            gap_budget=c.number_input("Total request budget",1,500,60)
            gap_oai=st.text_input("Thesis OAI-PMH URL (if selected)")
            gap_oai_set=st.text_input("Thesis OAI set (optional)")
        find_gaps=st.form_submit_button("Find field gaps",type="primary",width="stretch")
    if find_gaps:
        try:
            request=field_gap_request(gap_topic,[terms(line) for line in gap_terms.splitlines() if line.strip()] or None,[] if gap_local else gap_sources)
            request.config=RunConfig(**{**request.config.model_dump(),"local_documents_are_theses":gap_attested,
                "gap_max_candidates":gap_cap,"gap_per_study":gap_per,"gap_follow_up_queries":gap_follow,
                "max_downloads":0 if gap_local else gap_downloads,"per_source":gap_source_cap,"request_budget":gap_budget,
                "oai_url":gap_oai,"oai_set":gap_oai_set})
            run_request(request,gap_pdfs,gap_records,oa_key,core_key)
        except (ValidationError,ValueError,OSError) as exc:errors(exc)

with branches_tab:
    st.subheader("Locate a topic in its research field")
    st.write("Trace a specific topic from its broader domain to neighboring research topics. Choose an alternative placement when your topic crosses fields.")
    with st.form("topic_branches_form"):
        branch_topic=st.text_input("Specific research topic",placeholder="e.g. online clustering with prototype memory")
        with st.expander("Topic mapping limits"):
            a,b,c=st.columns(3)
            branch_matches=a.number_input("Alternative placements",1,5,3)
            branch_neighbors=b.number_input("Neighbors per placement",0,12,4)
            branch_sample=c.number_input("Publication sample limit",1,100,20)
        map_topic=st.form_submit_button("Map topic branches",type="primary",width="stretch")
    st.caption("OpenAlex taxonomy · no LLM calls. Solid branches show the source hierarchy; the dashed branch suggests where your input fits. Neighbors are peers, ordered by label similarity.")
    if map_topic:
        try:
            request=topic_branch_request(branch_topic)
            request.config=RunConfig(**{**request.config.model_dump(),"branch_max_matches":branch_matches,"branch_sibling_limit":branch_neighbors,"branch_work_limit":branch_sample})
            run_request(request,[],[],oa_key,core_key)
        except (ValidationError,ValueError,OSError) as exc:errors(exc)

result = st.session_state.get("result")
with branches_tab:
    if result is None or result.config.analysis_mode != "topic_branches":
        st.info("Enter a specific topic above to build a research branch map.")
    else:
        mapping=result.topic_branches
        placements=mapping.get("placements",[])
        if not placements:
            st.info("No source-backed placement found. Try a broader topic or an English equivalent, and inspect retrieval errors below.")
        else:
            selected=st.selectbox("Suggested taxonomy placement",range(len(placements)),format_func=lambda i:f"{i+1}. {placements[i]['topic_name']} · {placements[i]['supporting_work_count']} sampled publications",key="branch_choice_"+result.run_id)
            placement=placements[selected]
            st.write(" → ".join(node["name"] for node in placement["path"]))
            svg=branch_svg(mapping,selected)
            mobile_svg=branch_svg(mapping,selected,width=360)
            st.markdown('<div class="branch-map-desktop" aria-label="Topic branch map">'+svg+'</div><div class="branch-map-mobile" aria-label="Compact topic branch map">'+mobile_svg+'</div>',unsafe_allow_html=True)
            st.caption(mapping["note"]+" An accessible text tree with full labels is available below.")
            if not placement["hierarchy_complete"]:st.warning("Some parent levels are unavailable. The displayed path omits missing levels.")
            with st.expander("Accessible text tree and source evidence"):
                st.code(tree_lines(branch_tree(mapping,selected)),language=None)
                for node in placement["path"]:
                    st.text(f"{node['kind'].capitalize()}: {node['name']}")
                    st.link_button("Open taxonomy source",node["id"])
                st.write(f"Basis: {placement['basis']}. Sampled publications supporting this placement: {placement['supporting_work_count']}.")
                for work in placement["supporting_works"]:
                    st.write(work["title"])
                    if work["id"].startswith("https://openalex.org/"):st.link_button("Open supporting publication",work["id"])
                st.write(f"Neighbors shown: {len(placement['siblings'])}; available in source: {placement['siblings_available'] if placement['siblings_available'] is not None else 'not retrieved'}.")
            a,b,c=st.columns(3)
            a.download_button("Download tree SVG",svg,"topic_branches.svg","image/svg+xml")
            b.download_button("Download branches JSON",json.dumps(mapping,ensure_ascii=False,indent=2),"topic_branches.json","application/json")
            c.download_button("Download branches report",branch_report(mapping),"topic_branches.md","text/markdown")
        with st.expander("Mapping coverage and retrieval errors"):
            st.json({"coverage":result.coverage,"errors":mapping.get("errors",[])})

with results_tab:
    if result is None:
        st.info("No active run. Execute a specification or load a saved run.")
    else:
        st.subheader(result.profile.title)
        c = result.coverage
        st.caption(f"run_id={result.run_id} / records={len(result.studies)} / abstracts={c.get('with_abstract', 0)} / full_texts={c.get('with_readable_full_text', 0)} / requests={c.get('http_requests', 0)}")
        st.caption("Proximity = 0.70 word + 0.30 character TF-IDF cosine × 100. Uncalibrated; not novelty or probability.")
        for warning in result.warnings:
            st.warning(warning)
        if result.studies:
            a, b = st.columns([2, 1])
            search = a.text_input("filter.title_or_doi", placeholder="Substring match")
            minimum = b.number_input("filter.min_score", 0.0, 100.0, 0.0, step=1.0)
            visible = [s for s in result.studies if s.score >= minimum and (not search or search.casefold() in (s.title+s.doi).casefold())]
            rows = [{"score": s.score, "title": s.title, "year": s.year, "groups": f"{sum(bool(g) for g in s.concept_matches)}/{len(s.concept_matches)}",
                     "evidence": "full_text" if s.pages_read else "abstract" if s.abstract else "title", "type": s.type, "doi": s.doi} for s in visible]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={"score": st.column_config.NumberColumn(format="%.1f"), "title": st.column_config.TextColumn(width="large")})
            st.caption("Scroll the table horizontally for additional fields. Select a study below to inspect its evidence.")
            if visible:
                ids = {study.id: study for study in visible}
                ident = st.selectbox("study.id", list(ids), format_func=lambda key: f"{ids[key].score:.1f} / {ids[key].title}")
                study = ids[ident]
                st.text(study.title)
                st.caption(f"{'; '.join(study.authors) or 'Authors unavailable'} / {study.year or 'unknown year'} / {', '.join(study.sources)}")
                if study.url.startswith(("https://", "http://")):
                    st.link_button("Open source", study.url)
                st.json({"id": study.id, "score": study.score, "word_score": study.word_score, "character_score": study.character_score,
                         "concept_matches": study.concept_matches, "mechanism_matches": study.mechanism_matches, "dimension_matches": study.dimension_matches,
                         "full_text_status": study.full_text_status, "pages_read": study.pages_read, "pages_total": study.pages_total}, expanded=False)
                if study.full_text_note:
                    st.info(study.full_text_note)
                for i, evidence in enumerate(study.evidence, 1):
                    label = f"evidence[{i}] / {evidence.kind}" + (f" / PDF page {evidence.page}" if evidence.page else "")
                    with st.expander(label, expanded=i == 1):
                        st.text(evidence.text)
                        st.caption("matched_terms: " + (", ".join(evidence.matched_terms) or "none"))
                if study.duplicate_candidates:
                    st.info("Possible duplicate records retained for review: " + ", ".join(study.duplicate_candidates))
            else:
                st.info("No records match the current display filters.")
        with st.expander("coverage.json / request log"):
            st.json(result.coverage)
            st.dataframe(pd.DataFrame(result.search_log), hide_index=True, width="stretch")

with gaps_tab:
    if result is not None and result.config.analysis_mode=="field_gaps":
        st.caption(f"run_id={result.run_id} / source-reported candidates={len(result.gap_candidates)} / current openness=unverified")
        if not result.gap_candidates:
            st.info("No explicit gap statements found in accessible thesis text. This is not evidence that the field has no gaps. Check topic terms, thesis metadata, and full-text access.")
        else:
            rows=[{"id":gap.id,"category":gap.category,"statement":gap.statement,"sources":gap.support_count,"follow_up":gap.verification_status} for gap in result.gap_candidates]
            st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
            by_id={gap.id:gap for gap in result.gap_candidates}
            gap_id=st.selectbox("gap.id",list(by_id))
            selected_gap=by_id[gap_id]
            st.text(selected_gap.statement)
            st.caption("Current status: author-reported and unverified. Evidence below identifies who reported the limitation and when.")
            for evidence in selected_gap.evidence:
                with st.expander(f"{evidence.title} / {evidence.year or 'unknown year'} / {evidence.kind}"+(f" / PDF page {evidence.page}" if evidence.page else " / page unavailable"),expanded=True):
                    st.text(evidence.quote)
                    if evidence.truncated:st.caption("This is a bounded excerpt. Inspect the original source page for full context.")
                    st.caption(f"study_id={evidence.study_id} / section={evidence.section or 'unidentified'} / type_basis={evidence.source_type_basis}")
                    if evidence.url.startswith(("https://","http://")):st.link_button("Open thesis source",evidence.url,key="gap_source_"+selected_gap.id+evidence.study_id)
            related={study.id:study for study in result.gap_related_studies}
            st.write("Follow-up search: "+selected_gap.verification_status)
            st.code(selected_gap.follow_up_query,language=None)
            for ident in selected_gap.related_work_ids:
                if ident in related:
                    study=related[ident]
                    st.text(f"Related work for review: {study.title} ({study.year or 'unknown'})")
                    if study.url.startswith(("https://","http://")):st.link_button("Review related work",study.url,key="gap_related_"+selected_gap.id+ident)
        with st.expander("Gap analysis coverage"):
            st.json(result.gap_analysis)
        from lacuna.export import build_gap_report
        a,b=st.columns(2)
        a.download_button("Field gaps .json",json.dumps([gap.model_dump() for gap in result.gap_candidates],ensure_ascii=False,indent=2),f"lacuna_{result.run_id}.field_gaps.json","application/json",width="stretch")
        b.download_button("Field gaps report .md",build_gap_report(result),f"lacuna_{result.run_id}.field_gaps.md","text/markdown",width="stretch")
    else:
        st.info("No active field-gap run. Enter a topic above, or load a saved field-gap run from Runs.")

with artifacts_tab:
    st.subheader("Portable research artifacts")
    if result is None:
        st.info("Run a specification to generate ZIP packages and result JSON.")
    else:
        a, b, c = st.columns(3)
        a.download_button("Full package .zip", st.session_state.full_package, f"lacuna_{result.run_id}.zip", "application/zip", type="primary", width="stretch")
        b.download_button("Compact package .zip", st.session_state.compact_package, f"lacuna_{result.run_id}_compact.zip", "application/zip", width="stretch")
        c.download_button("Result .json", result.model_dump_json(indent=2), f"lacuna_{result.run_id}.json", "application/json", width="stretch")
        st.caption(f"Full: {len(result.studies)} records. Separate evidence files: {min(len(result.studies), result.config.package_studies)}. Compact portfolio: {min(len(result.studies), result.config.compact_studies)} records; all records listed in catalogue.csv.")
    st.download_button("ASSISTANT_PROMPT.md", ASSISTANT_PROMPT, "ASSISTANT_PROMPT.md", "text/markdown")
    with st.expander("ASSISTANT_PROMPT.md / interpret the output"):
        st.code(ASSISTANT_PROMPT, language=None)
    st.caption("Original PDFs and credentials are excluded. Profiles, excerpts, and local filenames may appear in exports. Review before sharing.")

with runs_tab:
    st.subheader("Local run store")
    if DB.exists():
        with sqlite3.connect(str(DB)) as connection:
            entries = connection.execute("SELECT id,created,title FROM runs ORDER BY created DESC LIMIT 50").fetchall()
        if entries:
            mapping = {row[0]: row for row in entries}
            chosen = st.selectbox("run.id", list(mapping), format_func=lambda key: f"{mapping[key][1][:16]} UTC / {mapping[key][2]}")
            if st.button("Load run"):
                with sqlite3.connect(str(DB)) as connection:
                    body = connection.execute("SELECT body FROM runs WHERE id=?", (chosen,)).fetchone()[0]
                activate_result(RunResult.model_validate_json(body))
                st.rerun()
        else:
            st.info("No saved runs.")
    else:
        st.info("No saved runs. Completed discoveries are stored locally.")
