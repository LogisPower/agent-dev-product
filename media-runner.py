import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime/media-libs'))
def main(config):
    import av
    path=Path(config['path']);result={'streams':[]}
    formats={'.wav':'wav','.mp3':'mp3','.m4a':'mov','.mp4':'mov','.mov':'mov','.webm':'matroska','.ogg':'ogg','.flac':'flac'}
    if path.suffix.lower() not in formats:raise ValueError('Unsupported audio/video format')
    with av.open(str(path),format=formats[path.suffix.lower()],options={'protocol_whitelist':'file,pipe','enable_drefs':'0'}) as media:
        result.update(format=media.format.name,duration_seconds=float(media.duration/av.time_base) if media.duration else None)
        if result['duration_seconds'] and result['duration_seconds']>600:raise ValueError('Audio/video processing limit: 10 minutes')
        for stream in media.streams:
            result['streams'].append({'type':stream.type,'codec':stream.codec_context.name,'frames':stream.frames})
        if media.streams.video:
            frame=next(media.decode(video=0),None)
            if frame:
                image=frame.to_image();image.thumbnail((640,640));image.convert('RGB').save(config['thumbnail']);result['thumbnail']=Path(config['thumbnail']).name
    if config.get('transcribe'):
        model_path=ROOT/'runtime/whisper-tiny.en'
        if not (model_path/'model.bin').exists():raise ValueError('Missing capability: Whisper model. Download Systran/faster-whisper-tiny.en into runtime/whisper-tiny.en using Prepare transcription.py')
        from faster_whisper import WhisperModel
        import numpy as np
        chunks=[];sample_count=0
        with av.open(str(path),format=formats[path.suffix.lower()],options={'protocol_whitelist':'file,pipe','enable_drefs':'0'}) as audio:
            resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
            for frame in audio.decode(audio=0):
                for sample in resampler.resample(frame):
                    values=sample.to_ndarray().flatten();sample_count+=len(values)
                    if sample_count>16000*600:raise ValueError('Transcription limit: 10 minutes')
                    chunks.append(values)
        samples=np.concatenate(chunks).astype(np.float32)/32768.0 if chunks else np.zeros(0,dtype=np.float32)
        model=WhisperModel(str(model_path),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
        segments,info=model.transcribe(samples,beam_size=1,vad_filter=True)
        result['language']=info.language;result['transcript']=' '.join(s.text.strip() for s in segments)[:30000]
    return result
try:print(json.dumps(main(json.load(sys.stdin))))
except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
