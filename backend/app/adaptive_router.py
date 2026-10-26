"""Additive API surface for the existing Learning OS."""
from fastapi import APIRouter
from fastapi import HTTPException
import sqlite3
import json
from uuid import uuid4
from .ai.schemas import StrictModel
from .db import connect
from .domain import adaptive_teaching as teaching


class PrerequisiteInput(StrictModel):
    prerequisite_skill_id: str
    target_skill_id: str
    basis: str


def teaching_router(path):
    router=APIRouter(prefix='/api/teaching',tags=['Adaptive Teaching'])

    @router.get('/goals')
    def goals():
        with connect(path) as db:
            teaching.guard(db)
            items=[]
            for row in db.execute("SELECT id,name FROM learning_skills WHERE status='active' ORDER BY sort_order,id"):
                order=teaching.prerequisite_order(db,row['id'])
                counts={n:len(teaching.questions(db,n)) for n in order}
                items.append({'id':row['id'],'name':row['name'],'ready':all(c>=4 for c in counts.values()),'question_counts':counts})
            return {'goals':items}

    @router.post('/sessions')
    def start(body:teaching.StartTeaching):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            return teaching.start(db,body)

    @router.post('/prerequisites')
    def prerequisite(body:PrerequisiteInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE');teaching.guard(db)
            source=teaching.skill(db,body.prerequisite_skill_id);target=teaching.skill(db,body.target_skill_id)
            if not body.basis.strip():raise HTTPException(422,'请说明前置关系的教学依据')
            try:
                db.execute('''INSERT INTO learning_relations(id,framework_id,source_skill_id,relation_type,target_skill_id,metadata_json,created_at)
                  VALUES(?,?,?,'prerequisite',?,?,?) ON CONFLICT(framework_id,source_skill_id,relation_type,target_skill_id) DO NOTHING''',
                  (str(uuid4()),source['framework_id'],source['id'],target['id'],json.dumps({'basis':body.basis,'curated':True},ensure_ascii=False),teaching.now()))
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409,'前置关系形成环，未保存') from exc
            return {'order':teaching.prerequisite_order(db,target['id'])}

    @router.get('/review/{attempt_id}')
    def review_remediation(attempt_id:str):
        with connect(path) as db:
            teaching.guard(db)
            att=db.execute("SELECT * FROM attempts WHERE id=? AND mode='REVIEW' AND submitted_at IS NOT NULL",(attempt_id,)).fetchone()
            if not att:raise HTTPException(404,'复习作答不存在')
            correct=att['corrected_correct'] if att['corrected_correct'] is not None else att['correct']
            if correct:return {'goals':[]}
            items=[]
            for row in db.execute("SELECT DISTINCT s.id,s.name FROM learning_skills s JOIN question_skill_bindings b ON b.learning_skill_id=s.id WHERE b.question_id=? AND b.status='active'",(att['question_id'],)):
                counts=[len(teaching.questions(db,n)) for n in teaching.prerequisite_order(db,row['id'])]
                if all(c>=4 for c in counts):items.append(dict(row))
            return {'goals':items}

    @router.get('/sessions/{sid}')
    def get_session(sid:str):
        with connect(path) as db:
            return teaching.view(db,sid)

    @router.post('/sessions/{sid}/actions')
    async def action(sid:str,body:teaching.TeachingAction):
        return await teaching.act(path,sid,body)

    return router
