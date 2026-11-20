import json, os, subprocess, sys
from pathlib import Path
from time import perf_counter
from backend.coaching.execution import local_course_intent_candidate
from backend.course_intent import course_intent_state,course_intent_questions,load_vega_reader,learner_course_score,is_first_student_turn
from scripts.evals import evaluate_retrieval as ev
from scripts.evals.evaluate_course_intent_learn import split_messages,evaluate_routes,select_threshold
here=Path(__file__).parent
old=Path('/tmp/course-intent-by-turn.zip')
os.environ['HF_HUB_OFFLINE']='1'
ev._block_network()
from laya import Learner

def read_file(name):
    for i,line in enumerate((here/name).read_text().splitlines(),1):
        if not line.strip(): continue
        label, content = line.split(' ',1)
        parts=content.split(' || ')
        assert label in ('+','-') and len(parts) in (1,3)
        msg=parts[0]
        history=[dict(role=role,text=text) for role,text in zip(('user','assistant'),parts[1:])]
        yield dict(id=f'{name}-{i:03d}',message=msg,history=history,selected_sources=[],attachments=[],stage='problem_identification',synthetic=True,expected_scope='course' if label=='+' else 'none',expected_decision='retrieve' if label=='+' else 'skip')

def classify(row):
    d=ev.gate_decision(row)
    return d.retrieve,local_course_intent_candidate(row['message'],intent=d.intent,
            evidence_scoped=bool(d.scope_cleared or row['attachments'] or row['selected_sources']), searched=d.retrieve)
def encode(row):
    return course_intent_state(row['message'],row['history'],titles)
materials = ev.load_materials()
titles=ev.eval_course_titles(materials)
messages = ev.load_messages(materials=materials)
splits=split_messages(messages)
supplement=list(read_file('training.txt'))
assert not {r['message'].casefold() for r in messages} & {r['message'].casefold() for r in supplement}
orig=[r for r in splits['train'] if classify(r)[1]]
addition=[r for r in supplement if classify(r)[1]]
print('Fit old + synthetic labels',len(orig),len(addition),flush=True)
started=perf_counter()
reader=load_vega_reader(Path('/tmp/codesign-laya-learn.UivsBY/model'))
model=Learner(course_intent_questions(),examples=[(encode(r),{'retrieval':'course_evidence' if r['expected_scope']=='course' else 'no_course_evidence'}) for r in orig+addition],reader=reader,auto=False,cache=0)
model.save_bundle(here/'sol-learner.zip')
print('Fit seconds',round(perf_counter()-started,1),flush=True)
models={k:Learner(bundle=p,reader=reader,auto=False,cache=0) for k,p in [('original',old),('sol',here/'sol-learner.zip')]}
def score(rows, keys):
    output=[]
    for row in rows:
        baseline,eligible=classify(row)
        result=dict(id=row['id'],expected=row['expected_decision'],expected_scope=row['expected_scope'],baseline_retrieve=baseline,eligible=eligible,first_turn=is_first_student_turn(row['history']),gate=None)
        for key in keys:
            started=perf_counter()
            result[key], result[f'{key}_readout']=learner_course_score(models[key].decide(encode(row))) if eligible else (None,None)
            result[f'{key}_ms']=round((perf_counter()-started)*1000,2) if eligible else None
        output.append(result)
    return output
cal=score(splits['calibration'],['sol'])
original=json.loads(Path('/tmp/course-intent-by-turn.json').read_text())['thresholds_from_calibration']
sol=select_threshold(cal,'sol')
assert sol is not None
sol_first=select_threshold(cal,'sol',continuing_cutoff=sol)
cutoffs={'original':(original['learn'],original['learn_first_turn']),'sol':(sol,sol_first)}
print('Cutoffs',cutoffs,flush=True)
fresh=list(read_file('evaluation.txt'))
norm=lambda s:' '.join(s.casefold().strip(' ?.!').split())
assert not {norm(r['message']) for r in fresh} & {norm(r['message']) for r in supplement+messages}
assert len({norm(r['message']) for r in fresh})==len(fresh)
fresh_rows=score(fresh,list(models))
historical=score(splits['holdout'],['sol'])
for r,s in zip(historical,json.loads(Path('/tmp/course-intent-by-turn.json').read_text())['holdout_rows'],strict=True):
    assert r['id']==s['id']
    r['original']=s['learn']
def metrics(rows):
    return {'gate':evaluate_routes(rows,'gate',1),**{k:evaluate_routes(rows,k,v[0],first_turn_threshold=v[1]) for k,v in cutoffs.items()}}
report=dict(training_counts=dict(original=len(orig),sol_eligible=len(addition),sol_authored=len(supplement)),training_report=model.report,cutoffs=cutoffs,fresh=metrics(fresh_rows),historical=metrics(historical),fresh_rows=fresh_rows,historical_rows=historical,calibration_rows=cal)
(here/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if not k.endswith('_rows')},indent=2),flush=True)
