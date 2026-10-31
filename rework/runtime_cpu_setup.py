"""Explicit local CPU profile attachment. No loading, grant creation or fallback."""
import atexit,json,sys
from pathlib import Path
def configure(app,root,reasoning):
    profile=Path(root)/'local-cpu-profile.json'
    if not profile.exists():
        app.state.local_model_configuration_notice='Optional CPU worker profile is not installed.'
        return
    collector=None
    try:
        if profile.stat().st_size>64000:raise ValueError('Profile bound')
        value=json.loads(profile.read_text(encoding='utf-8'))
        if set(value)!={'schema_version','measurement','enable_text_worker'} or value['schema_version']!=1 or type(value['enable_text_worker']) is not bool:raise ValueError('Invalid profile schema')
        from cpu_identity_collector import CpuIdentityCollector
        from cpu_vision_provider import install_verified_cpu_vision
        if str(Path(root).parent) not in sys.path:sys.path.append(str(Path(root).parent))
        from inference_gate import inference_slot
        collector=CpuIdentityCollector(value['measurement'])
        collector.open_verified(reuse_measured_resident=True)
        install_verified_cpu_vision(app,measured=value['measurement'],collector=collector,lock=lambda:inference_slot(Path(root).parent/'runtime/inference.lock',timeout=0),reasoning=reasoning,enable_text_worker=value['enable_text_worker'])
        app.state.cpu_collector=collector;atexit.register(collector.close)
        app.state.local_model_configuration_notice='Resident CPU profile attached; dispatch rechecks identity, resource reserves and slot. No model was loaded.'
    except Exception as error:
        if collector:collector.close()
        app.state.local_model_configuration_notice='Optional CPU profile unavailable ('+type(error).__name__+');27B remains available. No model load or fallback attempted.'
