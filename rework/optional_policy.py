"""Current optional policy facade; no grants when absent, malformed or disabled."""
import copy,json
from pathlib import Path
from system_summary import SCRIPTS
ROOT=r'C:\Users\LOGIS_USER\Documents\LogisWorkspaces'
class PolicyCredentials(dict):
 def __init__(self,base,policy_path,projects,workspace_current):
  super().__init__(copy.deepcopy(base));self.path=Path(policy_path);self.projects=tuple(projects);self.workspace_current=workspace_current
 def _grant(self):
  try:
   if not self.workspace_current():return None
   with self.path.open('rb') as f:raw=f.read(16001)
   if len(raw)>16000:return None
   g=json.loads(raw)
   if set(g)!={'schema_version','enabled','workspace_root','project_ids','system_summary_read','network_metadata'}:return None
   if type(g['schema_version']) is not int or g['schema_version']!=1 or g['enabled'] is not True or g['workspace_root']!=ROOT:return None
   ids=g['project_ids'];tools=g['system_summary_read']
   if type(ids) is not list or not ids or any(type(x) is not str for x in ids) or len(set(ids))!=len(ids) or set(ids)!=set(self.projects):return None
   if type(tools) is not list or any(type(x) is not str or x not in SCRIPTS for x in tools) or len(set(tools))!=len(tools):return None
   if type(g['network_metadata']) is not bool:return None
   return g
  except (OSError,ValueError,TypeError,KeyError):return None
 def items(self):
  grant=self._grant();rows=[]
  for key,original in super().items():
   value=copy.deepcopy(original)
   for field in ('system_summary_read','network_read','network_endpoints'):value.pop(field,None)
   if grant and value.get('write') is True and value.get('projects') and set(value['projects']).issubset(grant['project_ids']):
    value.update(system_summary_read=list(grant['system_summary_read']),network_read=grant['network_metadata'],network_endpoints=[])
   rows.append((key,value))
  return rows

def network_current(permissions):
 if permissions.get('network_read') is not True:return False
 callback=getattr(permissions,'current_summary_scope',None)
 if not callable(callback):return False
 try:
  now=callback()
  return now.get('network_read') is True and bool(permissions.get('projects')) and set(permissions['projects']).issubset(now.get('projects',[]))
 except Exception:return False
