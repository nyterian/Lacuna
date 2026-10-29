"""Source-backed topic placement; web SVG and terminal trees share one structure."""
from __future__ import annotations

from collections import Counter
from html import escape
import re
import textwrap
import uuid

from .models import RunResult, utcnow
from .net import WebClient
from pathlib import Path
from rapidfuzz.fuzz import token_set_ratio

API = "https://api.openalex.org"
NOTE = "Suggested placement from a bounded publication search, not a definitive classification. Sibling topics are peers, not subtopics of your input."


def topic_branch_request(topic):
    from .models import ResearchRequest, ResearchProfile, RunConfig
    return ResearchRequest(profile=ResearchProfile(title=topic, description=f"Locate the research topic {topic} within the OpenAlex domain, field, subfield and topic hierarchy.", concept_groups=[[topic[:160]]]),
                           config=RunConfig(analysis_mode="topic_branches", sources=["openalex"], citation_rounds=0, max_downloads=0))


def _entity(value, kind):
    if not isinstance(value, dict):
        return None
    ident = str(value.get("id", ""))
    patterns = {"topic": r"T\d+", "domain": r"domains/\d+", "field": r"fields/\d+", "subfield": r"subfields/\d+"}
    suffix = ident.removeprefix("https://openalex.org/")
    if not re.fullmatch(patterns[kind], suffix) or not value.get("display_name"):
        return None
    return {"id": "https://openalex.org/"+suffix, "name": str(value["display_name"])[:500], "kind": kind}


def run_topic_branches(profile, config, *, db_path=None, openalex_key="", progress=None, client=None):
    if "openalex" not in config.sources:
        raise ValueError("Topic branching requires the OpenAlex source and internet access (or cached responses).")
    progress = progress or (lambda *_: None)
    own_client = client is None
    client = client or WebClient(Path(db_path or "data/research.sqlite"), config.request_budget, config.use_cache)
    result = RunResult(run_id=uuid.uuid4().hex[:12], started_at=utcnow(), profile=profile, config=config)
    start = len(client.log)
    data = {"query": profile.title, "source": "OpenAlex", "source_documentation": "https://help.openalex.org/data/topics/", "status": "no_matches", "placements": [], "sampled_works": 0, "note": NOTE, "errors": []}
    params = {"search": profile.title, "per_page": config.branch_work_limit}
    if openalex_key:
        params["api_key"] = openalex_key
    try:
        progress(.1, "Searching publications for topic placement")
        works = []
        try:
            response = client.json(API+"/works", params=params, source="openalex_branches", label=f"Topic placement: {profile.title}")
            works = response.get("results", [])
            data["sampled_works"] = len(works)
            data["total_search_matches"] = response.get("meta", {}).get("count")
        except (RuntimeError, ValueError) as exc:
            data["errors"].append(str(exc))
        counts = Counter(); topics = {}; evidence = {}
        for work in works:
            topic = work.get("primary_topic") or {}
            entity = _entity(topic, "topic")
            if not entity:
                continue
            ident = entity["id"]
            topics.setdefault(ident, topic)
            counts[ident] += 1
            evidence.setdefault(ident, []).append({"id": str(work.get("id", "")), "title": str(work.get("display_name") or work.get("title") or "Untitled"), "year": work.get("publication_year"), "doi": str(work.get("doi") or "")})
        basis = "sampled_publications_primary_topic"
        if not topics:
            progress(.35, "Trying direct taxonomy search")
            try:
                response = client.json(API+"/topics", params={**params, "per_page": config.branch_max_matches}, source="openalex_branches", label=f"Taxonomy fallback: {profile.title}")
                for topic in response.get("results", []):
                    if entity := _entity(topic, "topic"):
                        topics[entity["id"]] = topic
                basis = "direct_taxonomy_search"
            except (RuntimeError, ValueError) as exc:
                data["errors"].append(str(exc))
        ordered = sorted(topics, key=lambda ident: (-counts[ident], list(topics).index(ident)))[:config.branch_max_matches]
        for i, ident in enumerate(ordered):
            progress(.4+.45*(i+1)/max(1,len(ordered)), "Reading taxonomy paths and neighboring topics")
            raw = topics[ident]
            detail_ok = False
            try:
                detail = client.json(API+"/topics/"+ident.rsplit("/",1)[-1], params={"api_key":openalex_key} if openalex_key else {}, source="openalex_branches", label=f"Topic hierarchy: {ident}")
                if _entity(detail,"topic") and _entity(detail,"topic")["id"] == ident:
                    raw = {**raw, **detail}
                    detail_ok = True
            except (RuntimeError, ValueError) as exc:
                data["errors"].append(str(exc))
            path = [node for kind in ("domain","field","subfield") if (node := _entity(raw.get(kind),kind))]
            path.append(_entity(raw,"topic"))
            siblings = []; seen = {ident}
            for sibling in raw.get("siblings") or []:
                entity = _entity(sibling,"topic")
                if entity and entity["id"] not in seen:
                    siblings.append(entity);seen.add(entity["id"])
            siblings.sort(key=lambda node: (-token_set_ratio(profile.title+" "+path[-1]["name"],node["name"]), node["name"]))
            data["placements"].append({"topic_id":ident,"topic_name":path[-1]["name"],"path":path,"basis":basis,"supporting_work_count":counts[ident],"supporting_works":evidence.get(ident,[])[:5],"neighbor_ordering":"lexical_label_similarity", "siblings":siblings[:config.branch_sibling_limit],"siblings_available":len(siblings) if detail_ok else None,"hierarchy_complete":len(path)==4,"topic_detail_retrieved":detail_ok})
        data["status"] = "partial" if data["placements"] and data["errors"] else "ok" if data["placements"] else "failed" if data["errors"] else "no_matches"
        if not data["placements"]:
            result.warnings.append("No source-backed placement found. Try a broader topic, an English equivalent, or configure an OpenAlex API key; no hierarchy was invented.")
        if data["errors"]:
            result.warnings.append("Some taxonomy requests failed; inspect topic_branches.errors and search_log. Available paths may be incomplete.")
        if config.sources != ["openalex"]:
            result.warnings.append("Topic branching uses OpenAlex only; other configured sources are not queried.")
        result.topic_branches = data
        result.search_log = client.log[start:]
        result.completed_at = utcnow()
        result.coverage = {"analysis_mode":"topic_branches","scope":"bounded_topic_placement","sampled_works":data["sampled_works"],"placement_count":len(data["placements"]),"work_sample_limit":config.branch_work_limit,"placement_limit":config.branch_max_matches,"sibling_limit":config.branch_sibling_limit,"http_requests":client.used,"request_budget":config.request_budget,"request_budget_reached":client.used>=config.request_budget,"limits":[NOTE,"Publication search relevance and classification may be imperfect. Missing hierarchy levels are omitted, not inferred.","Neighbor lists are bounded; no completeness or probability is claimed."]}
        client.save_run(result)
        progress(1., "Topic tree ready")
        return result
    finally:
        if own_client:
            client.close()


def branch_tree(data, index=0):
    """Common tree consumed by both renderers. Never place peers under the query."""
    placements = data.get("placements", [])
    if not placements:
        return {"label":"No source-backed placement found", "kind":"empty", "children":[]}
    placement = placements[index]
    root = {"label":"Research taxonomy", "kind":"root", "children":[]}
    parent = root
    for node in placement["path"]:
        child = {"label":node["name"], "kind":node["kind"], "id":node["id"], "children":[]}
        parent["children"].append(child)
        if node["kind"]=="topic":
            child["children"].append({"label":data["query"], "kind":"query", "children":[]})
            # Only attach documented siblings to an available subfield parent.
            if parent["kind"]=="subfield":
                parent["children"].extend({"label":s["name"],"kind":"peer","id":s["id"],"children":[]} for s in placement["siblings"])
        parent=child
    return root


def tree_lines(tree):
    lines = [tree["label"]]
    def walk(node, prefix):
        for i,child in enumerate(node["children"]):
            last=i==len(node["children"])-1
            suffix=" [suggested placement]" if child["kind"]=="query" else " [neighbor]" if child["kind"]=="peer" else ""
            lines.append(prefix+("└── " if last else "├── ")+child["label"]+suffix)
            walk(child,prefix+("    " if last else "│   "))
    walk(tree, "")
    return "\n".join(lines)


def rich_tree(data,index=0):
    from rich.tree import Tree
    from rich.text import Text
    def render(node):
        suffix=" [suggested placement]" if node["kind"]=="query" else " [neighbor]" if node["kind"]=="peer" else ""
        value=Tree(Text(node["label"]+suffix,style="bold bright_cyan" if node["kind"]=="query" else "default"),guide_style="bright_black")
        for child in node["children"]:value.add(render(child))
        return value
    return render(branch_tree(data,index))


def branch_svg(data,index=0,width=1040):
    tree=branch_tree(data,index);rows=[]
    def flatten(node,depth,parent=None):
        row=len(rows);rows.append((node,depth,parent))
        for child in node["children"]:flatten(child,depth+1,row)
    flatten(tree,0)
    indent=24 if width<600 else 68
    left=16 if width<600 else 26
    height=100+len(rows)*86
    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="max-width:100%;height:auto" role="img" aria-labelledby="title desc">', '<title id="title">Topic branch map</title>',f'<desc id="desc">{escape(tree_lines(tree))}</desc>',f'<rect width="{width}" height="{height}" fill="#080A0D"/>']
    for i,(node,depth,parent) in enumerate(rows):
        x=left+depth*indent;y=30+i*86
        if parent is not None:
            pdepth=rows[parent][1];px=left+pdepth*indent+12;py=30+parent*86+62
            svg.append(f'<path d="M {px} {py} V {y+31} H {x}" fill="none" stroke="#596574" stroke-width="1.5"'+(' stroke-dasharray="5 4"' if node['kind']=='query' else '')+'/>')
        active=node["kind"]=="query";topic=node["kind"]=="topic"
        svg.append(f'<rect x="{x}" y="{y}" width="{width-x-24}" height="62" rx="3" fill="{ "#182B24" if active else "#11151B"}" stroke="{ "#B4DFC4" if active or topic else "#39424F"}"/>')
        category={"root":"Overview","query":"Your input · suggested placement","peer":"Neighboring topic"}.get(node['kind'],node['kind'].capitalize())
        svg.append(f'<text x="{x+14}" y="{y+18}" fill="#A3ADBA" font-family="Times New Roman,serif" font-size="12">{escape(category)}</text>')
        lines=textwrap.wrap(node["label"],width=max(16,(width-x-54)//8))[:2]
        for j,line in enumerate(lines):
            # Full label is retained in title, JSON and the text tree.
            if j==1 and len(' '.join(lines))<len(node['label']):line=line.rstrip(' .')+'…'
            svg.append(f'<text x="{x+14}" y="{y+37+j*17}" fill="#E3E8EF" font-family="Times New Roman,serif" font-size="16">{escape(line)}</text>')
        svg.append(f'<title>{escape(node["label"])}</title>')
    legend="Solid: taxonomy. Dashed: suggested placement." if width<600 else "Solid branches: OpenAlex taxonomy. Dashed branch: suggested input placement."
    svg.append(f'<text x="{left}" y="{height-15}" fill="#A3ADBA" font-family="Times New Roman,serif" font-size="12">{legend}</text></svg>')
    return ''.join(svg)


def branch_report(data):
    from .export import md
    lines=["# Topic branches", "", md(data.get("query","")), "", NOTE, "", f"Status: {data.get('status','unknown')}. Sampled publications: {data.get('sampled_works',0)}.", ""]
    for i,placement in enumerate(data.get("placements",[])):
        lines.extend([f"## Placement {i+1}: {md(placement['topic_name'])}",f"Basis: {placement['basis']}. Supporting publications in this sample: {placement['supporting_work_count']}.","", "```text",tree_lines(branch_tree(data,i)).replace('```','~~~'),"```", "", "### Taxonomy sources"])
        lines.extend(f"- {md(node['name'])}: {node['id']}" for node in placement['path'])
        lines.extend(["", "### Supporting publications"])
        lines.extend(f"- {md(w['title'])} ({w.get('year') or 'year unknown'}): {w['id']}" for w in placement['supporting_works'])
        lines.extend(["", f"Neighboring topics shown: {len(placement['siblings'])}; available: {placement['siblings_available'] if placement['siblings_available'] is not None else 'not retrieved'}.", ""])
    if data.get('errors'):lines.extend(["## Retrieval errors", *[md(error) for error in data['errors']]])
    return '\n'.join(lines)+'\n'
