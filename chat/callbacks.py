import json
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def _serialize_message(msg) -> dict:
    if isinstance(msg, SystemMessage):
        return {"role": "system", "content": msg.content}
    elif isinstance(msg, HumanMessage):
        return {"role": "user", "content": msg.content}
    elif isinstance(msg, AIMessage):
        d = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            d["tool_calls"] = [
                {"name": tc.get("name"), "args": tc.get("args", {})}
                for tc in msg.tool_calls
            ]
        return d
    elif isinstance(msg, ToolMessage):
        return {
            "role": "tool",
            "tool_name": getattr(msg, "name", None),
            "content": msg.content,
        }
    return {"role": type(msg).__name__, "content": str(getattr(msg, "content", msg))}


class LLMCallbackHandler(BaseCallbackHandler):
    def __init__(self, session_pk: int):
        super().__init__()
        self.session_pk = session_pk  # scoped to session, not job
        self._pending: dict[str, list] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # messages is List[List[BaseMessage]] — one batch, take first
        self._pending[str(run_id)] = [_serialize_message(m) for m in messages[0]]

    def on_llm_end(self, response, *, run_id, **kwargs):
        from django.db.models import F
        from chat.models import LLMCall, ChatSession

        input_msgs = self._pending.pop(str(run_id), [])

        gen = (response.generations or [[]])[0]
        output_content = gen[0].text if gen else ""

        usage = (response.llm_output or {}).get("token_usage", {})
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        session = ChatSession.objects.get(pk=self.session_pk)
        LLMCall.objects.create(
            session=session,
            input_messages=input_msgs,
            output_content=output_content,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        # Mirror this call's usage onto the session's running totals via F() so
        # concurrent callbacks (tool-calling turns fire several LLM round-trips)
        # increment atomically instead of racing on a read-modify-write in Python.
        ChatSession.objects.filter(pk=self.session_pk).update(
            total_prompt_tokens=F('total_prompt_tokens') + (prompt_tokens or 0),
            total_completion_tokens=F('total_completion_tokens') + (completion_tokens or 0),
        )

        # Same running-total mirror one level up onto the owning job, so a job's
        # all-time LLM cost is readable without summing across its chat_sessions.
        from videos.models import VideoJob
        VideoJob.objects.filter(pk=session.job_id).update(
            total_prompt_tokens=F('total_prompt_tokens') + (prompt_tokens or 0),
            total_completion_tokens=F('total_completion_tokens') + (completion_tokens or 0),
        )
