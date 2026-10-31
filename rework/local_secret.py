"""Windows current-user DPAPI; no ACL or global credential changes."""
import ctypes
from ctypes import wintypes
class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
def transform(data,decrypt=False):
 buf=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
 fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
 if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise ctypes.WinError()
 try:return ctypes.string_at(out.data,out.size)
 finally:ctypes.windll.kernel32.LocalFree(out.data)
def protect(data):return transform(data)
def unprotect(data):return transform(data,True)
