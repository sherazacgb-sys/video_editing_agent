import os
import threading

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode, create_react_agent

from pipeline.tools import make_tools

_tool_lock = threading.Lock()


def _sequential_wrap(request, execute):
    with _tool_lock:
        return execute(request)


def build_agent(job_pk: int, video_path: str):
    tools = make_tools(job_pk, video_path)
    llm = ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
        model_kwargs={"reasoning_effort": "high"},
    )
    # handle_tool_errors=True converts any tool exception into a ToolMessage so
    # the agent can read the error and reply to the user instead of crashing the view.
    tool_node = ToolNode(tools, wrap_tool_call=_sequential_wrap, handle_tool_errors=True)
    return create_react_agent(llm, tool_node)
