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
        from chat.models import LLMCall, ChatSession

        input_msgs = self._pending.pop(str(run_id), [])

        gen = (response.generations or [[]])[0]
        output_content = gen[0].text if gen else ""

        usage = (response.llm_output or {}).get("token_usage", {})

        LLMCall.objects.create(
            session=ChatSession.objects.get(pk=self.session_pk),
            input_messages=input_msgs,
            output_content=output_content,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
