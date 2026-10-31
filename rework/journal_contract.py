"""Pure semantic journal validation. Checksums are integrity checks, not signatures."""
import hashlib,json,re
CONTRACT=('operation','path','destination','expected','new_hash')
BASE={'request_hash',*CONTRACT,'status','request_id','replayed'}
CHAIN={'journal_version','sequence','previous'}
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def contract(record):return {k:record[k] for k in CONTRACT}
def validate_record(record,request_id,path_validator):
    if not isinstance(record,dict) or not BASE<=set(record) or set(record)-BASE-CHAIN-{'backup'}:raise ValueError('Invalid journal record fields')
    if record['request_id']!=request_id or not re.fullmatch('[a-f0-9]{32}',request_id) or record['replayed'] is not False:raise ValueError('Invalid persisted request identity')
    if record['operation'] not in ('create','edit','move') or record['status'] not in ('prepared','mutation_started','verified'):raise ValueError('Invalid journal operation or state')
    path_validator(record['path'])
    if record['operation']=='move':
        path_validator(record['destination'])
        if record['destination'].casefold()==record['path'].casefold() or record['new_hash'] is not None:raise ValueError('Invalid move contract')
    elif record['destination'] is not None or not isinstance(record['new_hash'],str) or not re.fullmatch('[a-f0-9]{64}',record['new_hash']):raise ValueError('Invalid write contract')
    if record['operation']=='create':
        if record['expected'] is not None or record['status']=='mutation_started' or 'backup' in record:raise ValueError('Invalid create transition')
    elif not isinstance(record['expected'],str) or not re.fullmatch('[a-f0-9]{64}',record['expected']):raise ValueError('Missing source identity')
    if record['request_hash']!=digest(contract(record)):raise ValueError('Journal contract hash mismatch')
    if 'backup' in record and str(record['backup']).replace('\\','/')!='.logis/'+request_id+'.before':raise ValueError('Invalid recovery path')
    if record['status']=='prepared' and 'backup' in record:raise ValueError('Recovery copy cannot be claimed before mutation preparation')
    if record['operation']!='create' and record['status']!='prepared' and 'backup' not in record:raise ValueError('Missing recovery evidence')
    if set(record)&CHAIN:
        if not CHAIN<=set(record) or type(record['journal_version']) is not int or record['journal_version']!=2 or type(record['sequence']) is not int or record['sequence']<0:raise ValueError('Invalid transition chain fields')
        if record['previous'] is not None and (not isinstance(record['previous'],str) or not re.fullmatch('[a-f0-9]{64}',record['previous'])):raise ValueError('Invalid predecessor identity')
    return record
def validate_history(records):
    if not records:return None
    if len({digest(contract(r)) for r in records})!=1:raise ValueError('Conflicting immutable journal contracts')
    sequence=['prepared','verified'] if records[0]['operation']=='create' else ['prepared','mutation_started','verified']
    chained=[r for r in records if 'journal_version' in r]
    if chained:
        if len(chained)!=len(records):raise ValueError('Mixed legacy and chained transitions require inspection')
        ordered=sorted(records,key=lambda r:r['sequence'])
        if len(ordered)>len(sequence):raise ValueError('Duplicate or excessive journal transitions')
        previous=None
        for index,record in enumerate(ordered):
            if record['sequence']!=index or record['status']!=sequence[index] or record['previous']!=previous:raise ValueError('Journal transition gap, fork or invalid order')
            previous=digest(record)
        return ordered[-1]
    # Legacy receipts have no trustworthy order. Validate their contract and
    # legal state set; never invent sequence/chain assurance for them.
    phases={r['status'] for r in records}
    if len(records)>1 and (len(phases)!=len(records) or phases!=set(sequence[:len(phases)])):raise ValueError('Conflicting or incomplete legacy transitions')
    return max(records,key=lambda r:sequence.index(r['status']))
