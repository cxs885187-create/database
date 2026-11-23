"""LangChain MCP adapter with persistent sessions and validated tool arguments."""
import json
import sys
from contextlib import AsyncExitStack
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from .config import ROOT

class MCPGateway:
    def __init__(self,settings):
        self.settings = settings
        self.stack = AsyncExitStack()
        self.tools = {}

    async def start(self):
        connections = {mode:{'transport':'stdio','command':sys.executable,
                            'args':['-m','app.mcp_server','--database',str(self.settings.database_path),
                                    '--mode',mode,'--dictionary',str(self.settings.dictionary_enabled).lower()],
                            'cwd':str(ROOT)} for mode in ('read','write')}
        self.client = MultiServerMCPClient(connections)
        try:
            for mode in connections:
                session = await self.stack.enter_async_context(self.client.session(mode))
                for tool in await load_mcp_tools(session):
                    self.tools[tool.name] = tool
        except BaseException:
            await self.stack.aclose()
            raise
        if set(self.tools)!={'read_vocabulary','write_vocabulary'}:
            raise RuntimeError('Expected exactly one read and one write MCP tool')

    async def close(self):
        await self.stack.aclose()

    async def invoke(self,name,arguments):
        content = await self.tools[name].ainvoke(arguments)
        if isinstance(content,dict):
            return content
        if isinstance(content,list):
            text = '\n'.join(block.get('text','') for block in content if isinstance(block,dict))
        else:
            text = str(content)
        return json.loads(text)
