"""Transparent evidence portfolio selection; never changes proximity scores."""
from __future__ import annotations
from .query import contains


def select_portfolio(studies, profile, count):
    selected=[];reasons={}
    if not studies:return [],{}
    def take(study, reason):
        if study is None or study in selected or len(selected)>=count:return False
        selected.append(study);reasons[study.id]=[reason];return True
    take(studies[0],'highest_textual_proximity')
    relevant=[s for s in studies if sum(bool(g) for g in s.concept_matches)>=min(2,len(profile.concept_groups))]
    families={'comparators':[], 'mechanisms':[], 'coverage':[], 'full_text':[]}
    for title in profile.seed_titles:
        families['comparators'].append(('named_comparator_search:'+title,[s for s in studies if contains(s.title,title) or any(title in q for q in s.source_queries)]))
    for i,group in enumerate(profile.mechanism_groups):
        families['mechanisms'].append((f'mechanism_group:{i+1}',[s for s in studies if any(contains(s.title+' '+s.abstract,t) for t in group)]))
    historical=sorted([s for s in relevant if s.year is not None],key=lambda s:(s.year,-s.score))
    families['coverage'].append(('historical_topic_match',historical))
    for dtype in ('conference-paper','preprint','article','dissertation','review'):
        families['coverage'].append(('publication_type:'+dtype,[s for s in relevant if s.type==dtype]))
    families['full_text'].append(('readable_full_text',[s for s in relevant if s.pages_read]))
    while len(selected)<count:
        advanced=False
        for queue in families.values():
            while queue:
                reason,candidates=queue.pop(0)
                candidate=next((s for s in candidates if s not in selected),None)
                if take(candidate,reason):advanced=True;break
            if len(selected)>=count:break
        if not advanced:break
    for study in studies:
        if len(selected)>=count:break
        take(study,'score_rank_fill')
    return selected,reasons
