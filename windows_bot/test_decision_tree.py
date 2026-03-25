import unittest

from decision_tree import (
    build_web_search_decision,
    classify_social_intent,
    get_web_rules,
    get_social_reply_template,
    get_social_triggers,
    get_web_search_fragments,
    load_decision_tree,
)


class DecisionTreeTests(unittest.TestCase):
    def test_load_decision_tree_contains_social_and_web_sections(self):
        payload = load_decision_tree()

        self.assertIn("social", payload)
        self.assertIn("web_search", payload)
        self.assertIn("web_rules", payload)

    def test_social_triggers_are_loaded_from_json(self):
        self.assertIn("bonjour", get_social_triggers("greeting_triggers"))
        self.assertIn("aurevoir", get_social_triggers("closing_triggers"))
        self.assertIn("merci", get_social_triggers("short_acknowledgment_triggers"))

    def test_social_decision_and_templates_are_loaded_from_json(self):
        self.assertEqual(classify_social_intent("bonjour"), "greeting")
        self.assertEqual(classify_social_intent("aurevoir"), "closing")
        self.assertEqual(classify_social_intent("merci"), "short_ack")
        self.assertEqual(get_social_reply_template("greeting"), "Bonjour !")
        self.assertEqual(get_social_reply_template("closing", repeated=True), "")

    def test_web_search_fragments_are_loaded_from_json(self):
        self.assertIn("météo", get_web_search_fragments("trigger_fragments"))
        self.assertIn("et pour demain", get_web_search_fragments("followup_fragments"))
        self.assertIn("il pleut", get_web_search_fragments("context_indicators"))

    def test_web_search_decision_builds_followup_query_from_context(self):
        decision = build_web_search_decision(
            "et pour demain ?",
            "alice: quelle est la météo aujourd'hui à Lyon ?\nbot: Il pleut actuellement à Lyon.",
            mode="auto",
        )

        self.assertTrue(decision["enabled"])
        self.assertEqual(decision["reason"], "context_followup")
        self.assertEqual(decision["rule_id"], "context_followup")
        self.assertEqual(decision["query"], "météo demain à Lyon")

    def test_web_search_decision_prefers_structured_rule_over_generic_trigger(self):
        decision = build_web_search_decision(
            "dans l'actualité de la semaine, que dit Reuters en première page ?",
            "aucun",
            mode="auto",
        )

        self.assertTrue(decision["enabled"])
        self.assertEqual(decision["reason"], "structured_rule")
        self.assertEqual(decision["rule_id"], "reuters_front_page")
        self.assertEqual(decision["query"], "Reuters actualité première page")

    def test_web_search_decision_uses_city_rule_for_movies(self):
        decision = build_web_search_decision(
            "quels sont les films à l'affiche cette semaine à Lyon ?",
            "aucun",
            mode="auto",
        )

        self.assertTrue(decision["enabled"])
        self.assertEqual(decision["rule_id"], "movies_this_week_city")
        self.assertEqual(decision["query"], "films à l'affiche cette semaine Lyon")

    def test_web_search_decision_avoids_false_positive_on_chat_subject(self):
        decision = build_web_search_decision(
            "que peux tu me dire sur Dame_Gaby ?",
            "alice: qui est Dame_Gaby ?\nbot: Dame_Gaby joue à Valheim.",
            mode="auto",
        )

        self.assertFalse(decision["enabled"])
        self.assertEqual(decision["rule_id"], "no_match")

    def test_structured_web_rules_have_stable_ids(self):
        rule_ids = {rule.get("rule_id") for rule in get_web_rules()}

        self.assertIn("reuters_front_page", rule_ids)
        self.assertIn("best_film_2025", rule_ids)
        self.assertIn("movies_this_week_city", rule_ids)


if __name__ == "__main__":
    unittest.main()
