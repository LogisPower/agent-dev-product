"""Conservative compatibility receipts; no database or network side effects."""
import hashlib
import json
import math

PROFILE = {'schema':1,'model':'text-embedding-nomic-embed-text-v1.5',
           'dimensions':768,'query_prefix':'search_query: ',
           'document_prefix':'search_document: ','metric':'cosine'}
PROBES = ['Logis compatibility probe: violet observatory.',
          'Logis compatibility probe: amber orchard.']

def validate(vectors, count):
    if len(vectors)!=count: raise ValueError('Embedding response count mismatch')
    for vector in vectors:
        if len(vector)!=PROFILE['dimensions'] or any(type(x) not in (int,float) or not math.isfinite(x) for x in vector):
            raise ValueError('Embedding response dimension or numeric mismatch')
        if abs(math.sqrt(sum(x*x for x in vector))-1)>0.001:
            raise ValueError('Embedding response is not unit normalized')
    return vectors

def receipt(embed):
    # Behavioral signature checks both prefix paths. This does not attest binary identity.
    vectors=validate(embed(PROBES),2)+validate(embed(PROBES,query=True),2)
    payload={'profile':PROFILE,'probe_vectors':vectors}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'profile':dict(PROFILE),'behavior_sha256':digest}

def compatible(state,current,project):
    return (isinstance(state,dict) and state.get('project')==project
            and isinstance(state.get('collection'),str)
            and state['collection'].startswith('project_'+project+'_')
            and state.get('embedding_receipt')==current)

def blocked(reason):
    return {'matches':[],'status':'reindex_required','reason':reason,
            'message':'Explicit validation or reindex approval is required. Existing index preserved.'}
