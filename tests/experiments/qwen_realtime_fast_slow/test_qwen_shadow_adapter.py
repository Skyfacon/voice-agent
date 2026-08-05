from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Callable

import aiohttp

from experiments.qwen_realtime_fast_slow_web import (
    qwen_shadow_router_adapter as adapter_module,
)
from experiments.qwen_realtime_fast_slow_web.provider_context import CredentialHandle
from experiments.qwen_realtime_fast_slow_web.qwen_shadow_router_adapter import (
    FUNCTION_NAME,
    FakeShadowControlProvider,
    FakeShadowScript,
    QwenShadowRouterAdapter,
    SCHEMA_VERSION,
    ShadowAdapterConfig,
    ShadowRouteRequest,
    build_shadow_session_update,
)


API_KEY_SENTINEL = "PRIVATE_QWEN_SHADOW_CREDENTIAL_SENTINEL"


def run(coro):
    return asyncio.run(coro)


def valid_frame() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_focus_hint": "FOREGROUND_CHAT",
        "route_decision_hint": "FAST_ONLY",
        "foreground_act": "ANSWER",
        "task_like": False,
        "complexity_hint": "LOW",
        "evidence_uncertainty": "LOW",
        "risk_class": "LOW",
        "risk_tags": ["none"],
        "confidence": 0.94,
        "reply_candidate_text": "PRIVATE_TRANSIENT_CANDIDATE_SENTINEL",
    }


def request(index: int = 1) -> ShadowRouteRequest:
    return ShadowRouteRequest(
        request_id=f"request-{index}",
        turn_id=f"turn-{index}",
        utterance_id=f"utterance-{index}",
        asr_frame_ref=f"asr-frame://safe/{index}",
        transcript=f"PRIVATE_TRANSIENT_TRANSCRIPT_SENTINEL_{index}",
        task_focus_snapshot={
            "active_task_id": "task_qfs_1",
            "lifecycle": "PLANNING",
            "plan_version": 2,
            "pending_confirmation_scope": None,
        },
    )


def text_message(payload: object) -> SimpleNamespace:
    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(payload))


class ReactiveWebSocket:
    def __init__(
        self,
        *,
        response_mode: str = "valid",
        acknowledge_deletes: bool = True,
        acknowledge_cancel_terminal: bool = True,
    ) -> None:
        self.closed = False
        self.sent: list[dict[str, Any]] = []
        self.response_mode = response_mode
        self.acknowledge_deletes = acknowledge_deletes
        self.acknowledge_cancel_terminal = acknowledge_cancel_terminal
        self.incoming: asyncio.Queue[SimpleNamespace] = asyncio.Queue()
        self.incoming.put_nowait(text_message({"type": "session.created"}))
        self.incoming.put_nowait(text_message({"type": "session.updated"}))

    async def send_json(self, payload: dict[str, Any]) -> None:
        copied = json.loads(json.dumps(payload))
        self.sent.append(copied)
        event_type = copied.get("type")
        if event_type == "conversation.item.create":
            self.incoming.put_nowait(
                text_message(
                    {
                        "type": "conversation.item.created",
                        "item": {"id": copied["item"]["id"], "type": "message"},
                    }
                )
            )
        elif event_type == "response.create":
            self._enqueue_response()
        elif event_type == "response.cancel" and self.acknowledge_cancel_terminal:
            self.push(
                {
                    "type": "response.done",
                    "response": {
                        "id": "provider-response-1",
                        "status": "cancelled",
                    },
                }
            )
        elif event_type == "conversation.item.delete" and self.acknowledge_deletes:
            self.incoming.put_nowait(
                text_message(
                    {
                        "type": "conversation.item.deleted",
                        "item_id": copied["item_id"],
                    }
                )
            )

    async def receive(self) -> SimpleNamespace:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True

    def push(self, payload: object) -> None:
        self.incoming.put_nowait(text_message(payload))

    def _enqueue_response(self) -> None:
        response_id = "provider-response-1"
        item_id = "provider-function-item-1"
        call_id = "provider-call-1"
        self.push(
            {
                "type": "response.created",
                "response": {"id": response_id},
            }
        )
        if self.response_mode == "timeout":
            return
        if self.response_mode == "provider_error":
            self.push(
                {
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "code": "PRIVATE_PROVIDER_AUTH_CODE",
                        "message": (
                            "Authorization: Bearer "
                            "PRIVATE_PROVIDER_CREDENTIAL_SENTINEL"
                        ),
                    },
                }
            )
            return
        if self.response_mode == "ordinary_text":
            self.push(
                {
                    "type": "response.text.delta",
                    "response_id": response_id,
                    "delta": "ordinary provider text",
                }
            )
            self.push(
                {
                    "type": "response.done",
                    "response": {"id": response_id, "status": "completed"},
                }
            )
            return
        arguments = json.dumps(valid_frame(), separators=(",", ":"))
        split = len(arguments) // 2
        self.push(
            {
                "type": "response.output_item.added",
                "response_id": response_id,
                "item": {
                    "id": item_id,
                    "type": "function_call",
                    "call_id": call_id,
                    "name": FUNCTION_NAME,
                },
            }
        )
        for fragment in (arguments[:split], arguments[split:]):
            self.push(
                {
                    "type": "response.function_call_arguments.delta",
                    "response_id": response_id,
                    "item_id": item_id,
                    "call_id": call_id,
                    "delta": fragment,
                }
            )
        self.push(
            {
                "type": "response.function_call_arguments.done",
                "response_id": response_id,
                "item_id": item_id,
                "call_id": call_id,
                "name": FUNCTION_NAME,
                "arguments": arguments,
            }
        )
        self.push(
            {
                "type": "response.output_item.done",
                "response_id": response_id,
                "item": {
                    "id": item_id,
                    "type": "function_call",
                    "call_id": call_id,
                    "name": FUNCTION_NAME,
                    "arguments": arguments,
                },
            }
        )
        if self.response_mode == "second_function_call":
            self.push(
                {
                    "type": "response.output_item.added",
                    "response_id": response_id,
                    "item": {
                        "id": "provider-function-item-2",
                        "type": "function_call",
                        "call_id": "provider-call-2",
                        "name": FUNCTION_NAME,
                    },
                }
            )
        self.push(
            {
                "type": "response.done",
                "response": {"id": response_id, "status": "completed"},
            }
        )


class RecordingClientSession:
    def __init__(self, websocket: ReactiveWebSocket) -> None:
        self.websocket = websocket
        self.closed = False
        self.connect_calls: list[tuple[str, dict[str, Any]]] = []

    async def ws_connect(self, endpoint: str, **kwargs: Any) -> ReactiveWebSocket:
        self.connect_calls.append((endpoint, dict(kwargs)))
        return self.websocket

    async def close(self) -> None:
        self.closed = True


class SessionFactory:
    def __init__(self, sessions: list[RecordingClientSession]) -> None:
        self.sessions = sessions
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> RecordingClientSession:
        self.calls.append(dict(kwargs))
        if not self.sessions:
            raise AssertionError("unexpected extra ClientSession")
        return self.sessions.pop(0)


async def wait_until(predicate: Callable[[], bool], *, timeout: float = 1.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=timeout)


def make_adapter(
    monkeypatch,
    *websockets: ReactiveWebSocket,
    request_timeout: float = 0.2,
    delete_timeout: float = 0.05,
) -> tuple[QwenShadowRouterAdapter, list[RecordingClientSession]]:
    sessions = [RecordingClientSession(websocket) for websocket in websockets]
    factory = SessionFactory(list(sessions))
    monkeypatch.setattr(adapter_module.aiohttp, "ClientSession", factory)
    adapter = QwenShadowRouterAdapter(
        CredentialHandle(API_KEY_SENTINEL, "ws-safe-shadow"),
        config=ShadowAdapterConfig(
            connect_timeout_seconds=0.2,
            request_timeout_seconds=request_timeout,
            context_delete_timeout_seconds=delete_timeout,
        ),
    )
    return adapter, sessions


def test_real_adapter_connects_text_session_and_confirms_context_deletes(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket()
        adapter, sessions = make_adapter(monkeypatch, websocket)
        await adapter.connect()

        endpoint, connect_kwargs = sessions[0].connect_calls[0]
        assert endpoint == (
            "wss://ws-safe-shadow.cn-beijing.maas.aliyuncs.com/"
            "api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus"
        )
        assert connect_kwargs["headers"] == {
            "Authorization": f"Bearer {API_KEY_SENTINEL}"
        }
        assert websocket.sent[0] == build_shadow_session_update()
        assert "tool_choice" not in websocket.sent[0]["session"]

        result = await adapter.analyze(request())
        assert result.output_mode == "real"
        assert result.schema_valid is True
        assert result.proposal is not None
        assert result.proposal.route_decision_hint == "FAST_ONLY"
        assert result.request_id == "request-1"
        assert result.turn_id == "turn-1"
        assert result.utterance_id == "utterance-1"
        assert result.context_tainted is False
        assert result.context_delete_count == 2
        assert adapter.counters.context_delete_count == 2
        assert adapter.session_state == "connected"

        sent_types = [payload["type"] for payload in websocket.sent]
        assert sent_types == [
            "session.update",
            "conversation.item.create",
            "response.create",
            "conversation.item.delete",
            "conversation.item.delete",
        ]
        provider_text = websocket.sent[1]["item"]["content"][0]["text"]
        assert provider_text.count("PRIVATE_TRANSIENT_TRANSCRIPT_SENTINEL_1") == 1
        assert "task_qfs_1" not in provider_text
        assert '"active_task_ref":"task-' in provider_text
        assert '"current_plan_version":2' in provider_text
        assert "pending_confirmation_scope" not in provider_text
        assert websocket.sent[2] == {
            "type": "response.create",
            "response": {"modalities": ["text"]},
        }
        assert {
            payload["item_id"]
            for payload in websocket.sent
            if payload["type"] == "conversation.item.delete"
        } == {"shadow_input_00000001", "provider-function-item-1"}

        safe_serialized = json.dumps(result.to_safe_metadata(), sort_keys=True)
        assert API_KEY_SENTINEL not in safe_serialized
        assert "PRIVATE_TRANSIENT_TRANSCRIPT_SENTINEL" not in safe_serialized
        assert "PRIVATE_TRANSIENT_CANDIDATE_SENTINEL" not in safe_serialized
        assert "function_arguments" not in safe_serialized
        await adapter.close()
        assert websocket.closed is True
        assert sessions[0].closed is True

    run(scenario())


def test_real_adapter_rejects_a_genuine_second_function_call(monkeypatch) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(response_mode="second_function_call")
        adapter, _sessions = make_adapter(monkeypatch, websocket)
        await adapter.connect()

        result = await adapter.analyze(request())

        assert result.output_mode == "degraded"
        assert result.schema_valid is False
        assert result.proposal is None
        assert result.degraded_code == "multiple_function_calls"
        assert result.context_delete_count == 3
        await adapter.close()

    run(scenario())


def test_real_adapter_plain_text_is_degraded_without_proposal(monkeypatch) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(response_mode="ordinary_text")
        adapter, _sessions = make_adapter(monkeypatch, websocket)
        await adapter.connect()
        result = await adapter.analyze(request())

        assert result.output_mode == "degraded"
        assert result.schema_valid is False
        assert result.proposal is None
        assert result.degraded_code == (
            "shadow_ordinary_text_instead_of_function_call"
        )
        assert result.context_delete_count == 1
        await adapter.close()

    run(scenario())


def test_real_adapter_provider_error_is_allowlisted_without_raw_body(monkeypatch) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(response_mode="provider_error")
        adapter, _sessions = make_adapter(monkeypatch, websocket)
        await adapter.connect()
        result = await adapter.analyze(request())
        serialized = json.dumps(result.to_safe_metadata(), sort_keys=True)

        assert result.output_mode == "degraded"
        assert result.schema_valid is False
        assert result.proposal is None
        assert result.degraded_code == "shadow_provider_authentication_failed"
        assert "PRIVATE_PROVIDER_AUTH_CODE" not in serialized
        assert "PRIVATE_PROVIDER_CREDENTIAL_SENTINEL" not in serialized
        assert "Authorization" not in serialized
        assert "Bearer" not in serialized
        await adapter.close()

    run(scenario())


def test_real_adapter_timeout_sends_cancel_and_never_fabricates_proposal(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(response_mode="timeout")
        adapter, _sessions = make_adapter(
            monkeypatch,
            websocket,
            request_timeout=0.01,
        )
        await adapter.connect()
        result = await adapter.analyze(request(), timeout_seconds=0.01)

        assert result.output_mode == "degraded"
        assert result.schema_valid is False
        assert result.proposal is None
        assert result.degraded_code == "shadow_request_timeout"
        assert result.context_tainted is True
        assert adapter.counters.timeout_count == 1
        assert any(
            payload == {"type": "response.cancel"} for payload in websocket.sent
        )
        await adapter.close()

    run(scenario())


def test_real_adapter_delete_failure_taints_and_rebuilds_independent_connection(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        first_socket = ReactiveWebSocket(acknowledge_deletes=False)
        second_socket = ReactiveWebSocket(acknowledge_deletes=True)
        adapter, sessions = make_adapter(
            monkeypatch,
            first_socket,
            second_socket,
            delete_timeout=0.005,
        )
        await adapter.connect()

        first = await adapter.analyze(request(1))
        assert first.schema_valid is True
        assert first.proposal is not None
        assert first.output_mode == "degraded"
        assert first.degraded_code == "shadow_context_delete_unconfirmed"
        assert first.context_tainted is True
        assert adapter.counters.context_delete_failure_count == 1
        assert adapter.session_state == "degraded"

        second = await adapter.analyze(request(2))
        assert first_socket.closed is True
        assert sessions[0].closed is True
        assert len(sessions[1].connect_calls) == 1
        assert adapter.counters.context_rebuild_count == 1
        assert second.context_rebuild_count == 1
        assert second.output_mode == "real"
        assert second.schema_valid is True
        assert second.turn_id == "turn-2"
        assert adapter.session_state == "connected"
        await adapter.close()

    run(scenario())


def test_late_old_response_delta_is_discarded_after_request_completion(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket()
        adapter, _sessions = make_adapter(monkeypatch, websocket)
        await adapter.connect()
        result = await adapter.analyze(request())
        assert result.schema_valid is True
        before = adapter.counters.late_event_discard_count

        websocket.push(
            {
                "type": "response.function_call_arguments.delta",
                "response_id": "provider-response-1",
                "item_id": "provider-function-item-1",
                "call_id": "provider-call-1",
                "delta": "{}",
            }
        )
        await wait_until(
            lambda: adapter.counters.late_event_discard_count == before + 1
        )

        assert adapter.counters.late_event_discard_count == before + 1
        await adapter.close()

    run(scenario())


def test_real_control_cancel_waits_for_matching_terminal_and_counts_both(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(response_mode="timeout")
        adapter, _sessions = make_adapter(
            monkeypatch, websocket, request_timeout=1.0, delete_timeout=0.1
        )
        await adapter.connect()
        analysis = asyncio.create_task(adapter.analyze(request()))
        await wait_until(
            lambda: any(
                payload.get("type") == "response.create"
                for payload in websocket.sent
            )
        )

        assert await adapter.cancel_active_request() is True
        result = await asyncio.wait_for(analysis, timeout=1)

        assert result.output_mode == "degraded"
        assert result.proposal is None
        assert result.degraded_code in {
            "shadow_request_cancelled",
            "shadow_response_not_completed",
        }
        assert adapter.counters.cancel_request_count == 1
        assert adapter.counters.cancel_terminal_count == 1
        assert [
            payload for payload in websocket.sent if payload.get("type") == "response.cancel"
        ] == [{"type": "response.cancel"}]
        assert await adapter.cancel_active_request() is False
        await adapter.close()

    run(scenario())


def test_real_control_cancel_without_terminal_taints_and_never_claims_terminal(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        websocket = ReactiveWebSocket(
            response_mode="timeout", acknowledge_cancel_terminal=False
        )
        adapter, _sessions = make_adapter(
            monkeypatch, websocket, request_timeout=1.0, delete_timeout=0.01
        )
        await adapter.connect()
        analysis = asyncio.create_task(adapter.analyze(request()))
        await wait_until(
            lambda: any(
                payload.get("type") == "response.create"
                for payload in websocket.sent
            )
        )

        assert await adapter.cancel_active_request() is True
        result = await asyncio.wait_for(analysis, timeout=1)

        assert result.output_mode == "degraded"
        assert result.context_tainted is True
        assert adapter.context_tainted is True
        assert adapter.counters.cancel_request_count == 1
        assert adapter.counters.cancel_terminal_count == 0
        await adapter.close()

    run(scenario())


def test_fake_control_cancel_active_request_is_bounded_and_inactive_is_false() -> None:
    async def scenario() -> None:
        provider = FakeShadowControlProvider(
            [FakeShadowScript(delay_seconds=1.0)]
        )
        await provider.connect()
        assert await provider.cancel_active_request() is False

        analysis = asyncio.create_task(
            provider.analyze(request(), timeout_seconds=2.0)
        )
        await wait_until(lambda: provider._active_analysis_task is not None)
        assert await provider.cancel_active_request() is True
        result = await asyncio.wait_for(analysis, timeout=1)

        assert result.output_mode == "degraded"
        assert result.degraded_code == "shadow_request_cancelled"
        assert result.context_tainted is True
        assert provider.context_tainted is True
        assert provider.counters.cancel_request_count == 1
        assert await provider.cancel_active_request() is False
        await provider.close()

    run(scenario())
