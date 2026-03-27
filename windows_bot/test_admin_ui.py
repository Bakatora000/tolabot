import unittest

from admin_ui import (
    HTML_PAGE,
    build_conversation_graph_payload,
    build_facts_graph_payload,
    build_homegraph_payload,
)


class AdminUiGraphTests(unittest.TestCase):
    def test_html_page_blocks_viewer_switch_while_analysis_is_pending(self):
        self.assertIn("window.analysisInFlight = null;", HTML_PAGE)
        self.assertIn("function canOpenViewer(targetUserId, targetViewerLabel = targetUserId)", HTML_PAGE)
        self.assertIn('id="analysis-banner"', HTML_PAGE)
        self.assertIn("La navigation vers un autre viewer est temporairement verrouillée", HTML_PAGE)

    def test_html_page_places_viewer_actions_on_user_cards(self):
        self.assertNotIn('id="export-button"', HTML_PAGE)
        self.assertNotIn('id="export-review-button"', HTML_PAGE)
        self.assertNotIn('id="purge-button"', HTML_PAGE)
        self.assertIn('class="viewer-item-actions"', HTML_PAGE)
        self.assertIn('class="viewer-icon-button viewer-icon-button-export export-viewer-button"', HTML_PAGE)
        self.assertIn('class="viewer-icon-button viewer-icon-button-review export-review-viewer-button"', HTML_PAGE)
        self.assertIn('class="viewer-icon-button viewer-icon-button-danger purge-viewer-button"', HTML_PAGE)

    def test_html_page_uses_dynamic_homegraph_legend_items(self):
        self.assertIn("function getHomegraphLegendModel()", HTML_PAGE)
        self.assertIn("buildLegendItems(fullGraphData.links, 'kind', 'color', 'link')", HTML_PAGE)
        self.assertIn("La légende Homegraph reflète les types réellement présents", HTML_PAGE)

    def test_html_page_does_not_synthesize_channel_scoped_homegraph_viewers(self):
        self.assertNotIn("twitch:${currentChannel}:viewer:${shortId}", HTML_PAGE)
        self.assertIn("if (shortId && shortId.includes(':')) {", HTML_PAGE)
        self.assertIn("if (!shortId.includes(':')) {", HTML_PAGE)
        self.assertIn("if (matches.length === 1) {", HTML_PAGE)

    def test_html_page_omits_viewer_filter_for_centered_homegraph_requests(self):
        self.assertIn("const isCenteredHomegraph = graphKind === 'homegraph' && homegraphCenterNodeId !== '';", HTML_PAGE)
        self.assertIn("if (!isCenteredHomegraph) {", HTML_PAGE)
        self.assertIn("query.set('viewer', viewer);", HTML_PAGE)

    def test_html_page_raises_depth_for_ambiguous_homegraph_viewers(self):
        self.assertIn("if (homegraphCenterNodeId.startsWith('viewer:')) {", HTML_PAGE)
        self.assertIn("if (!centeredViewerId.includes(':')) {", HTML_PAGE)
        self.assertIn("homegraphMaxDepth = String(Math.max(2, parseInt(homegraphMaxDepth || '2', 10) || 2));", HTML_PAGE)

    def test_html_page_keeps_ambiguous_homegraph_viewers_in_graph_navigation(self):
        self.assertIn("function hasAmbiguousHomegraphLabel(node)", HTML_PAGE)
        self.assertIn("if (targetUser && !hasAmbiguousHomegraphLabel(node)", HTML_PAGE)

    def test_html_page_filters_centered_homegraph_to_connected_component(self):
        self.assertIn("function getConnectedComponentGraphData(data, rootNodeId)", HTML_PAGE)
        self.assertIn("if (graphKind === 'homegraph' && homegraphCenterNodeId) {", HTML_PAGE)
        self.assertIn("data = getConnectedComponentGraphData(data, homegraphCenterNodeId);", HTML_PAGE)

    def test_html_page_exposes_homegraph_enrichment_review_flow(self):
        self.assertIn("function renderHomegraphEnrichmentPanel()", HTML_PAGE)
        self.assertIn("Fusionner dans Homegraph", HTML_PAGE)
        self.assertIn("/homegraph-enrichment/merge", HTML_PAGE)
        self.assertIn("Fusion bloquée : la validation locale a retourné mergeable=false.", HTML_PAGE)

    def test_html_page_locks_homegraph_merge_after_success(self):
        self.assertIn("window.currentHomegraphMerged = false;", HTML_PAGE)
        self.assertIn("window.currentHomegraphMerged || !validation || validation.mergeable === false", HTML_PAGE)
        self.assertIn("Fusion déjà appliquée pour cette proposition Homegraph.", HTML_PAGE)

    def test_html_page_exposes_collapsible_recent_and_editor_panels(self):
        self.assertIn('id="recent-toggle-button"', HTML_PAGE)
        self.assertIn('id="editor-toggle-button"', HTML_PAGE)
        self.assertIn("function updateCollapsiblePanels()", HTML_PAGE)
        self.assertIn("function toggleRecentPanel()", HTML_PAGE)
        self.assertIn("function toggleEditorPanel()", HTML_PAGE)

    def test_build_conversation_graph_payload_links_turns_and_viewers(self):
        graph = {
            "channels": {
                "streamer": {
                    "turns": [
                        {
                            "turn_id": "t1",
                            "timestamp": "2026-03-26T10:00:00+00:00",
                            "speaker": "alice",
                            "message_text": "salut bob",
                            "bot_reply": "bonjour",
                            "event_type": "message",
                            "reply_to_turn_id": "",
                            "corrects_turn_id": "",
                            "target_viewers": ["bob"],
                        },
                        {
                            "turn_id": "t2",
                            "timestamp": "2026-03-26T10:01:00+00:00",
                            "speaker": "bob",
                            "message_text": "je réponds",
                            "bot_reply": "",
                            "event_type": "message",
                            "reply_to_turn_id": "t1",
                            "corrects_turn_id": "",
                            "target_viewers": [],
                        },
                    ]
                }
            }
        }

        payload = build_conversation_graph_payload(graph, viewer_filter="alice")

        node_ids = {node["id"] for node in payload["nodes"]}
        link_kinds = {link["kind"] for link in payload["links"]}
        self.assertIn("viewer:alice", node_ids)
        self.assertIn("turn:t1", node_ids)
        self.assertIn("turn:t2", node_ids)
        self.assertIn("authored", link_kinds)
        self.assertIn("targets", link_kinds)
        self.assertIn("reply_to", link_kinds)

    def test_build_facts_graph_payload_creates_fact_nodes(self):
        facts_memory = {
            "channels": {
                "streamer": {
                    "facts": [
                        {
                            "timestamp": "2026-03-26T10:00:00+00:00",
                            "subject": "MissCouette76",
                            "predicate": "alias",
                            "value": "aussi appelée MissCouette",
                            "source_speaker": "dame_gaby",
                            "verification_state": "third_party_reported",
                        }
                    ]
                }
            }
        }

        payload = build_facts_graph_payload(facts_memory, viewer_filter="misscouette76")

        self.assertEqual(payload["kind"], "facts")
        self.assertEqual(payload["stats"]["fact_count"], 1)
        self.assertTrue(any(node["kind"] == "fact" for node in payload["nodes"]))
        self.assertTrue(any(link["kind"] == "about" for link in payload["links"]))

    def test_build_homegraph_payload_preserves_contract_and_applies_colors(self):
        raw_payload = {
            "nodes": [
                {"id": "viewer:alice", "kind": "viewer", "label": "alice"},
                {"id": "game:valheim", "kind": "game", "label": "Valheim"},
            ],
            "links": [
                {"source": "viewer:alice", "target": "game:valheim", "kind": "plays"},
            ],
            "stats": {"node_count": 2, "link_count": 1},
            "meta": {"version": "v1", "center_node_id": "game:valheim", "truncated": True},
        }

        payload = build_homegraph_payload(raw_payload, viewer_filter="alice")

        self.assertEqual(payload["kind"], "homegraph")
        self.assertEqual(payload["meta"]["version"], "v1")
        self.assertEqual(payload["meta"]["center_node_id"], "game:valheim")
        self.assertTrue(payload["meta"]["truncated"])
        self.assertEqual(payload["stats"]["node_count"], 2)
        self.assertTrue(any(node["color"] for node in payload["nodes"]))
        self.assertEqual(payload["links"][0]["label"], "plays")


if __name__ == "__main__":
    unittest.main()
