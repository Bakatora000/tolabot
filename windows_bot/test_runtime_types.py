import unittest
from types import SimpleNamespace

from context_sources import make_context_source_result
from runtime_types import (
    ContextSourceResult,
    DecisionResult,
    MessagePreparation,
    NormalizedEvent,
    PromptPlan,
    QueuedMessageContext,
    RuntimeContextBundle,
    RuntimePipelineDeps,
)


class RuntimeTypesTests(unittest.TestCase):
    def test_decision_result_exposes_enabled_compatibility(self):
        decision = DecisionResult(
            decision="web_search",
            rule_id="weather_followup",
            reason="context_followup",
            needs_web=True,
            query="meteo demain a lyon",
        )

        self.assertTrue(decision["enabled"])
        self.assertEqual(decision["rule_id"], "weather_followup")
        self.assertEqual(decision.to_dict()["enabled"], True)

    def test_runtime_dataclasses_capture_target_contract(self):
        event = NormalizedEvent(
            event_id="evt_1",
            type="chat_message",
            channel="expevay",
            author="alice",
            timestamp="2026-03-25T18:00:00Z",
            text="@anneaunimouss salut",
        )
        source = ContextSourceResult(
            source_id="mem0",
            available=True,
            priority=80,
            confidence=0.74,
            stale=False,
            text_block="Contexte viewer: ...",
        )
        prompt = PromptPlan(
            system_block="system",
            viewer_block="viewer",
            conversation_block="conversation",
            web_block="web",
            style_block="style",
            source_trace=["local", "mem0"],
        )
        runtime_context = RuntimeContextBundle(
            viewer_context="viewer",
            global_context="conversation",
            web_context="web",
            context_source="local",
            sources=[source],
            conversation_mode="",
        )

        self.assertEqual(event.type, "chat_message")
        self.assertEqual(source.source_id, "mem0")
        self.assertEqual(prompt.source_trace, ["local", "mem0"])
        self.assertEqual(runtime_context.context_source, "local")

    def test_make_context_source_result_skips_empty_blocks(self):
        self.assertIsNone(
            make_context_source_result(
                "mem0",
                "aucun",
                priority=80,
                confidence=0.7,
            )
        )

    def test_runtime_pipeline_deps_capture_callable_contract(self):
        calls = []

        def persist_local_turn(**kwargs) -> None:
            calls.append(("local", kwargs["channel_name"], kwargs["author"]))

        def persist_local_and_remote_turn(**kwargs) -> None:
            calls.append(("remote", kwargs["channel_name"], kwargs["msg_id"]))

        def remember_remote_turn(channel_name: str, author: str, user_message: str, **kwargs) -> bool:
            calls.append(("remember", channel_name, author, user_message, kwargs.get("allow_remote", True)))
            return True

        def build_runtime_context_bundle(**kwargs) -> RuntimeContextBundle:
            return RuntimeContextBundle(
                viewer_context=kwargs.get("viewer_context", ""),
                global_context="",
                web_context="",
                context_source="local",
            )

        deps = RuntimePipelineDeps(
            persist_local_turn_fn=persist_local_turn,
            persist_local_and_remote_turn_fn=persist_local_and_remote_turn,
            remember_remote_turn_fn=remember_remote_turn,
            build_runtime_context_bundle_fn=build_runtime_context_bundle,
        )

        deps.persist_local_turn_fn(
            channel_name="expevay",
            author="alice",
            clean_viewer_message="salut",
            event_type="chat_message",
            related_viewer="",
            related_message="",
            reply_to_turn_id="",
            related_turn_id="",
        )
        deps.persist_local_and_remote_turn_fn(
            channel_name="expevay",
            author="alice",
            clean_viewer_message="salut",
            msg_id="msg-1",
            allow_remote=True,
            author_is_owner=False,
            event_type="chat_message",
            related_viewer="",
            related_message="",
            reply_to_turn_id="",
            related_turn_id="",
        )
        remembered = deps.remember_remote_turn_fn(
            "expevay",
            "alice",
            "salut",
            allow_remote=False,
        )
        bundle = deps.build_runtime_context_bundle_fn(viewer_context="viewer")

        self.assertTrue(remembered)
        self.assertEqual(bundle.viewer_context, "viewer")
        self.assertEqual(
            calls,
            [
                ("local", "expevay", "alice"),
                ("remote", "expevay", "msg-1"),
                ("remember", "expevay", "alice", "salut", False),
            ],
        )

    def test_queued_message_context_groups_runtime_state(self):
        queued_message = SimpleNamespace(
            payload=SimpleNamespace(broadcaster=SimpleNamespace(name="Expevay")),
            text="@AnneAuNimouss salut",
            clean_viewer_message="salut",
            author="alice",
            msg_id="msg-1",
            received_at=123.0,
        )
        prepared = MessagePreparation(
            resolved_text="salut",
            alias_context="",
            focus_context="",
            facts_context="",
            author_is_owner=False,
            event_type="chat_message",
            related_viewer="",
            related_message="",
            related_turn_id="",
            reply_to_turn_id="",
            riddle_related=False,
            riddle_thread_reset=False,
            riddle_thread_close=False,
            specialized_local_thread=False,
        )
        decision = DecisionResult(
            decision="model_reply",
            rule_id="model_reply_basic",
            reason="default",
        )
        deps = RuntimePipelineDeps(
            persist_local_turn_fn=lambda **kwargs: None,
            persist_local_and_remote_turn_fn=lambda **kwargs: None,
            remember_remote_turn_fn=lambda *args, **kwargs: True,
            build_runtime_context_bundle_fn=lambda **kwargs: RuntimeContextBundle(
                viewer_context="",
                global_context="",
                web_context="",
                context_source="local",
            ),
        )

        context = QueuedMessageContext(
            queued_message=queued_message,
            channel_name="expevay",
            prepared=prepared,
            decision=decision,
            pipeline_deps=deps,
        )

        self.assertEqual(context.queued_message.author, "alice")
        self.assertEqual(context.channel_name, "expevay")
        self.assertEqual(context.prepared.resolved_text, "salut")
        self.assertEqual(context.decision.rule_id, "model_reply_basic")


if __name__ == "__main__":
    unittest.main()
