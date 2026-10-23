"""Windows-account encrypted contact profile; no credentials or payment details."""
import ctypes,json
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FIELDS=('full_name','preferred_name','email','phone','company','job_title','address_line1','address_line2','city','region','postal_code','country','form_preferences')
class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
def crypt(data,decrypt=False):
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    dll=ctypes.WinDLL('crypt32',use_last_error=True)
    if decrypt:ok=dll.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:ok=dll.CryptProtectData(ctypes.byref(source),'Logis account profile',None,None,None,1,ctypes.byref(target))
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data,target.size)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree;free.argtypes=[ctypes.c_void_p];free(ctypes.cast(target.data,ctypes.c_void_p))
def read():
    path=ROOT/'Data/account-profile.dpapi'
    return json.loads(crypt(path.read_bytes(),True)) if path.exists() else {}
def save(data):
    values={key:str(data.get(key,'')).strip()[:2000 if key=='form_preferences' else 300] for key in FIELDS}
    path=ROOT/'Data/account-profile.dpapi';path.parent.mkdir(exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_bytes(crypt(json.dumps(values).encode()));temporary.replace(path)
    return {'saved':True}
def select(fields):
    if not isinstance(fields,list) or any(x not in FIELDS for x in fields):raise ValueError('Choose supported contact fields')
    profile=read()
    return {'fields':{key:profile.get(key,'') for key in fields},'instruction':'Use only for the user-requested form. Missing values must be requested, never invented. Show the filled values and obtain user confirmation before submitting a form. Never use this for credentials, financial accounts or identity-document fields.'}
