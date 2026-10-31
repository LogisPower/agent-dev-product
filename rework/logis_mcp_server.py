"""Logis MCP foundation: one benign read-only clock; STDIO only."""
import datetime,importlib.metadata
from mcp.server import MCPServer
from pydantic import BaseModel,ConfigDict
class ClockResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    utc:str
    host_time:str
    host_timezone:str
    source:str
    accuracy:str
    effect:str
if importlib.metadata.version('mcp')!='2.3.0':raise RuntimeError('Pinned MCP SDK version required')
server=MCPServer('Logis bounded local tools',version='1.0.0',log_level='ERROR')
@server.tool(structured_output=True)
def clock_snapshot() -> ClockResult:
    """Return current host/UTC time. No network time verification, filesystem or shell access."""
    now=datetime.datetime.now(datetime.timezone.utc);local=now.astimezone()
    return ClockResult(utc=now.isoformat(),host_time=local.isoformat(),host_timezone=str(local.tzinfo),source='host system clock',accuracy='not independently verified',effect='none')
if __name__=='__main__':server.run(transport='stdio')
