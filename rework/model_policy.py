"""Staged policy, not a scheduler or launcher. No imports of model SDKs."""
from dataclasses import dataclass
import math
import re
from local_model_config import PORT, ALIAS, WEIGHT, CONTEXT

@dataclass(frozen=True)
class Model:
    key: str
    port: int
    alias: str
    weight: str
    projector: str | None
    context_limit: int

MODELS = {
    'reasoning': Model('bonsai27',PORT,ALIAS,WEIGHT,None,CONTEXT),
    'vision': Model('bonsai9vision',8082,'bonsai2-9b-vision','Ternary-Bonsai-2-9B-PQ2_0.gguf','Ternary-Bonsai-2-9B-mmproj-Q8_0.gguf',8192),
}

def select(role, *, has_images=False):
    if role not in ('reasoning','vision','lightweight'):
        raise ValueError('Unsupported model role; no automatic external fallback')
    if has_images and role != 'vision':
        raise ValueError('Images require explicit vision routing')
    return MODELS['vision' if role in ('vision','lightweight') else 'reasoning']

CONFIG_KEYS={'model_key','alias','weight_name','weight_sha256','projector_name',
    'projector_sha256','backend_sha256','cache_k','cache_v','slots','context',
    'gpu_identity'}
REQUEST_KEYS={'input_tokens','output_tokens','image_count','image_pixels'}

def _number(x):
    return not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x)

def _integer(x,minimum=0):
    return type(x) is int and x>=minimum

def _digest(x):
    return isinstance(x,str) and re.fullmatch('[a-f0-9]{64}',x) is not None

def admission(sample, profile, *, now, selected_role, endpoint, request, slots, canceled=False):
    """Called INSIDE existing shared inference lock, never evidence to load a model.

    Profile is a measured, versioned per-model incremental inference requirement.
    Unknown inputs fail closed. Live external workloads are NOT controlled by this
    lock. A future caller must re-sample before sending and retain lock to finish.
    """
    if canceled:return {'allowed':False,'reason':'canceled'}
    if not isinstance(selected_role,str) or selected_role not in ('reasoning','vision','lightweight'):
        return {'allowed':False,'reason':'unregistered_model'}
    model=select(selected_role)
    if not all(isinstance(x,dict) for x in (sample,profile,endpoint,request)) or not _number(now):
        return {'allowed':False,'reason':'invalid_contract'}
    expected_profile={'schema_version','measurement_id','measured_at','valid_until',
        'config','envelope','incremental_ram_mib','incremental_vram_mib','incremental_commit_mib'}
    if set(profile)!=expected_profile or profile['schema_version']!=1 or type(profile['schema_version']) is not int:
        return {'allowed':False,'reason':'invalid_profile_schema'}
    cfg=profile['config']; envelope=profile['envelope']
    if not isinstance(cfg,dict) or set(cfg)!=CONFIG_KEYS or set(endpoint)!=CONFIG_KEYS:
        return {'allowed':False,'reason':'invalid_identity_schema'}
    if endpoint!=cfg:return {'allowed':False,'reason':'endpoint_profile_mismatch'}
    if (cfg['model_key']!=model.key or cfg['alias']!=model.alias or
        cfg['weight_name']!=model.weight or cfg['projector_name']!=model.projector):
        return {'allowed':False,'reason':'registry_identity_mismatch'}
    if not _digest(cfg['weight_sha256']) or not _digest(cfg['backend_sha256']):
        return {'allowed':False,'reason':'unknown_binary_identity'}
    if (model.projector and not _digest(cfg['projector_sha256'])) or (not model.projector and cfg['projector_sha256'] is not None):
        return {'allowed':False,'reason':'unknown_projector_identity'}
    if (cfg['cache_k'] not in ('f16','q8_0','q4_0') or cfg['cache_v'] not in ('f16','q8_0','q4_0')
        or type(cfg['slots']) is not int or cfg['slots']!=1
        or not _integer(cfg['context'],1) or cfg['context']>model.context_limit
        or not isinstance(cfg['gpu_identity'],str) or not cfg['gpu_identity'].strip()):
        return {'allowed':False,'reason':'unsupported_configuration'}
    # Enumerated cache types are profile keys, not a claim backend support was tested.
    if (not isinstance(profile['measurement_id'],str) or not profile['measurement_id'].strip()
        or not _number(profile['measured_at']) or not _number(profile['valid_until'])
        or not profile['measured_at']<=now<=profile['valid_until']
        or not 0<profile['valid_until']-profile['measured_at']<=86400):
        return {'allowed':False,'reason':'expired_or_unverified_profile'}
    if (not isinstance(envelope,dict) or set(envelope)!=REQUEST_KEYS or set(request)!=REQUEST_KEYS
        or any(not _integer(x) for x in [*envelope.values(),*request.values()])
        or envelope['input_tokens']<1 or envelope['output_tokens']<1
        or request['input_tokens']<1 or request['output_tokens']<1
        or any(request[k]>envelope[k] for k in REQUEST_KEYS)
        or envelope['input_tokens']+envelope['output_tokens']>cfg['context']
        or request['input_tokens']+request['output_tokens']>cfg['context']
        or bool(request['image_count'])!=bool(request['image_pixels'])
        or bool(envelope['image_count'])!=bool(envelope['image_pixels'])
        or (request['image_count'] and selected_role!='vision')
        or (envelope['image_count'] and not model.projector)):
        return {'allowed':False,'reason':'workload_outside_measured_envelope'}
    if not isinstance(slots,list) or len(slots)!=cfg['slots'] or any(not isinstance(x,dict) or x.get('is_processing') is not False for x in slots):
        return {'allowed':False,'reason':'busy_or_unknown_slots'}
    fields=('observed_at','ram_available_mib','commit_used_mib','commit_limit_mib','gpu_total_mib','gpu_used_mib','gpu_shared_mib')
    requirements=('incremental_ram_mib','incremental_vram_mib','incremental_commit_mib')
    for obj,names in ((sample,fields),(profile,requirements)):
        if any(isinstance(obj.get(k),bool) or not isinstance(obj.get(k),(int,float)) or not math.isfinite(obj[k]) or obj[k]<0 for k in names):
            return {'allowed':False,'reason':'unknown_capacity_or_profile'}
    if sample.get('gpu_identity') != cfg['gpu_identity'] or not sample.get('gpu_identity'):
        return {'allowed':False,'reason':'unverified_profile_or_device'}
    if not 0 <= now-sample['observed_at'] <= 5:return {'allowed':False,'reason':'stale_capacity'}
    if sample['gpu_used_mib']>sample['gpu_total_mib'] or sample['commit_used_mib']>sample['commit_limit_mib']:
        return {'allowed':False,'reason':'inconsistent_capacity'}
    # Conservative provisional reserves, not measured performance guarantees.
    if sample['ram_available_mib'] < profile['incremental_ram_mib']+4096:return {'allowed':False,'reason':'ram_reserve'}
    if sample['commit_limit_mib']-sample['commit_used_mib'] < profile['incremental_commit_mib']+4096:return {'allowed':False,'reason':'commit_reserve'}
    if sample['gpu_total_mib']-sample['gpu_used_mib'] < profile['incremental_vram_mib']+2048:return {'allowed':False,'reason':'gpu_reserve'}
    if sample['gpu_shared_mib']>1024:return {'allowed':False,'reason':'gpu_spill_pressure'}
    return {'allowed':True,'reason':'bounded_resident_inference_only','measurement_id':profile['measurement_id']}
