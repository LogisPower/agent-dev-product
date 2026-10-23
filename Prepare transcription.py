from pathlib import Path
import os,sys
root=Path(__file__).resolve().parent
os.environ['HF_HOME']=str(root/'runtime/hf-cache')
os.environ['HF_HUB_DISABLE_XET']='1'
sys.path.insert(0,str(root/'runtime/media-libs'))
from huggingface_hub import snapshot_download
snapshot_download('Systran/faster-whisper-tiny.en',local_dir=root/'runtime/whisper-tiny.en',allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*'])
print('Whisper tiny English model ready for local CPU transcription.')
