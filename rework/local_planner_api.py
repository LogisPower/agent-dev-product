"""Scoped opt-in proposal routes. No provider setup or worker startup."""
from fastapi import Depends
from pydantic import BaseModel,ConfigDict,Field


class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    goal:str=Field(min_length=1,max_length=1000)
    paths:list[str]=Field(min_length=1,max_length=2)


class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    task:str=Field(pattern='^[a-f0-9]{32}$')
    version:int=Field(ge=1,strict=True)


class DiscoveryRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    query:str=Field(min_length=1,max_length=200)
    directory:str=Field(default='',max_length=180)


class DiscoveryPlan(Decision):
    goal:str=Field(min_length=1,max_length=1000)
    paths:list[str]=Field(min_length=1,max_length=2)
    allow_completed:bool=Field(default=False,strict=True)


class AuthorRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    goal:str=Field(min_length=1,max_length=1000)
    path:str=Field(min_length=1,max_length=180)
    context_paths:list[str]=Field(default_factory=list,max_length=2)


class AnalysisRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=170)
    goal:str=Field(min_length=1,max_length=1000)
    path:str=Field(min_length=1,max_length=180)


class AnalysisPlan(Decision):
    goal:str=Field(min_length=1,max_length=1000)
    paths:list[str]=Field(min_length=1,max_length=2)


class MixedRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    title:str=Field(min_length=1,max_length=120)
    selections:list[Decision]=Field(min_length=1,max_length=8)
    allow_unsupported:bool=Field(default=False,strict=True)


class VerificationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    key:str=Field(min_length=1,max_length=180)
    paths:list[str]=Field(min_length=1,max_length=8)


def register(app,loop,scope,check,guarded,public,admission):
    from local_analysis import LocalAnalysis
    analysis=getattr(loop,'analysis',None) or LocalAnalysis(loop)
    from local_discovery import LocalDiscovery
    discovery=getattr(loop,'discovery',None) or LocalDiscovery(loop)
    from local_author import LocalAuthor
    author=LocalAuthor(loop,lambda:getattr(app.state,'foundation',None))
    from local_mixed_plan import MixedPlans
    mixed=MixedPlans(loop,author)
    from project_verification import ProjectVerification
    verification=ProjectVerification(loop)
    def planner():
        value=getattr(loop,'planner',None)
        if value is None:raise ValueError('Local text-only planner is not configured')
        return value
    @app.post('/api/projects/{project}/local-planning/analyze')
    def analyze(project:str,body:AnalysisRequest,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(analysis.submit(project,body.key,body.goal,body.path,identity))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/from-analysis')
    def from_analysis(project:str,body:AnalysisPlan,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(analysis.plan(project,body.task,body.version,body.goal,body.paths,identity))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/propose')
    def propose(project:str,body:Request,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(planner().submit(project,body.key,body.goal,body.paths,identity))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/discover')
    def discover(project:str,body:DiscoveryRequest,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(discovery.submit(project,body.key,body.query,body.directory,identity))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/from-discovery')
    def from_discovery(project:str,body:DiscoveryPlan,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(discovery.plan(project,body.task,body.version,body.goal,body.paths,identity,body.allow_completed))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/author')
    def new_file(project:str,body:AuthorRequest,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(author.submit(project,body.key,body.goal,body.path,body.context_paths,identity))
        return guarded(run)
    @app.get('/api/projects/{project}/local-planning/mixed')
    def mixed_status(project:str,permissions=Depends(scope)):
        def run():
            check(project,permissions)
            identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return mixed.list(project,identity)
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/mixed')
    def mixed_submit(project:str,body:MixedRequest,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            with admission(project):return mixed.submit(project,body.key,body.title,[v.model_dump() for v in body.selections],identity,body.allow_unsupported)
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/verify')
    def verify(project:str,body:VerificationRequest,permissions=Depends(scope)):
        def run():
            check(project,permissions,True);identity=permissions.get('_dispatch_identity')
            if not identity:raise PermissionError('Authenticated principal required')
            return public(verification.submit(project,body.key,body.paths,identity))
        return guarded(run)
    @app.post('/api/projects/{project}/local-planning/{action}')
    def decision(project:str,action:str,body:Decision,permissions=Depends(scope)):
        def run():
            check(project,permissions,action!='author-workflow')
            if action=='author-workflow':return author.workflow(project,body.task)
            if action=='accept-author':
                with admission(project):return author.accept(project,body.task,body.version)
            if action=='accept':
                with admission(project):result=planner().accept(project,body.task,body.version)
                result['tasks']=[public(task) for task in result['tasks']];return result
            if action=='cancel':
                task=loop.ledger.get(project,body.task)
                if task['kind'] not in ('local_plan','local_discovery','local_author','local_verify','local_analysis'):raise ValueError('Not a planning task')
                return public(loop.ledger.cancel(project,body.task))
            if action=='resume-analysis':return public(analysis.resume(project,body.task,body.version))
            raise ValueError('Unknown proposal action')
        return guarded(run)
