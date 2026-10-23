import base64,json,urllib.request
def analyze(folder,file_path,prompt='Describe the image and its important details.'):
    file=SAFE(folder,file_path)
    if file.suffix.lower() not in ('.png','.jpg','.jpeg','.webp') or file.stat().st_size>5_000_000:raise ValueError('Vision accepts PNG, JPEG or WebP up to 5 MB')
    mime='image/jpeg' if file.suffix.lower() in ('.jpg','.jpeg') else 'image/'+file.suffix[1:]
    content=[{'type':'text','text':str(prompt)[:4000]},{'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(file.read_bytes()).decode()}}]
    data={'model':'bonsai2-9b-vision','messages':[{'role':'user','content':content}],'max_tokens':1800,'temperature':0.2,'chat_template_kwargs':{'enable_thinking':False}}
    req=urllib.request.Request('http://127.0.0.1:8082/v1/chat/completions',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=240) as response:result=json.load(response)
    return {'model':'Bonsai 2 9B Vision','source':file_path,'analysis':result['choices'][0]['message']['content']}
