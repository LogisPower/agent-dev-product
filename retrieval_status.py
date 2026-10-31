"""User-facing retrieval outcomes, independent of model wording."""
def notice(result):
    if not isinstance(result,dict):return 'Retrieval unavailable. No verified document evidence was returned.'
    status=result.get('status')
    if status=='empty':return 'No indexable document content is available. No document evidence was retrieved.'
    if status=='reindex_required':return 'Retrieval unavailable: this project needs explicit index validation or reindex approval. No document evidence was retrieved; the existing index is preserved.'
    if result.get('error') or status=='unavailable':return 'Retrieval unavailable. No verified document evidence was returned. Check the local embedding service and retry when ready.'
    if not result.get('matches'):return 'No matching document evidence was retrieved.'
    return None

def tool_notice(name,result):
    if name=='rag_index':return 'Indexing requires your explicit action in Artifacts. No index was changed.'
    return notice(result) if name=='rag_search' else None
