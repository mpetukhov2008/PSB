import unittest

from psb.assistant import Assistant, ModelError, RequestError, check_evidence, validate_request
from test_assistant import FakeModel, corpus
from psb.knowledge import KnowledgeBase


class RequestTests(unittest.TestCase):
    def test_conflicting_dates_require_clarification(self):
        with self.assertRaisesRegex(RequestError, "отличается"):
            validate_request({"question": "Срок на 2026-03-01", "event_date": "2026-08-01"})

    def test_oversized_history_rejected_with_action(self):
        with self.assertRaisesRegex(RequestError, "новый диалог"):
            validate_request({"question": "Договор?", "history": [{"role": "user", "content": "x" * 6000}] * 6})

    def test_malformed_role_is_input_error(self):
        with self.assertRaises(RequestError):
            validate_request({"question": "Договор?", "history": [{"role": [], "content": "x"}]})

    def test_empty_refusal_cannot_be_verified(self):
        with self.assertRaises(ModelError):
            check_evidence({"status": "insufficient", "message": "", "claims": []}, [])

    def test_malformed_review_blocked(self):
        class BadReview(FakeModel):
            def complete(self, system, payload):
                return [] if "answer" in payload else super().complete(system, payload)
        result = Assistant(KnowledgeBase(corpus()), BadReview()).answer({"question": "Согласование договора"})
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["claims"], [])


if __name__ == "__main__":
    unittest.main()
