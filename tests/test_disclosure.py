"""Offline tests for the AI disclosure parameters (no network).

Run: python -m unittest tests/test_disclosure.py
"""

import unittest

from verda import AiDisclosure, ComplianceError, ContentDetails, DecodeResult, Job, VerdaClient, VerdaError


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    """Records requests and answers them from a queue."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.answers.pop(0)


def client(answers):
    c = VerdaClient(api_key="vk_test")
    c._session = FakeSession(answers)
    c.poll_interval = 0
    return c


DONE_JOB = {
    "job": {
        "job_id": "j1", "job_type": "encode", "status": 3, "download_url": "https://dl",
        "provenance": {"watermark_ref": "ref-1", "verify_url": "https://verda.ai/abc", "private_details_salt": "s4lt"},
        "ai_disclosure": {"provider_name": "Acme", "system_name": "Imagine", "system_version": "3.2",
                          "ai_involvement": "generated", "generated_at": "1793188800"},
        "details": {"license": "CC0", "prompt": "a cat"},
    }
}


class EncodeSendsEverything(unittest.TestCase):
    def test_disclosure_profile_and_metadata_reach_the_api(self):
        c = client([FakeResp(200, {"job_id": "j1"}), FakeResp(200, DONE_JOB)])
        result = c.encode(
            url="https://cdn.example.com/a.png",
            metadata='{"k": 1}',
            title="Autumn",
            ai_disclosure=AiDisclosure(ai_involvement="generated", system_name="Imagine", system_version="3.2"),
            details=ContentDetails(license="CC0", prompt="a cat", private_fields=["license"]),
            compliance_profile="both",
        )
        body = c._session.calls[0][2]["json"]
        self.assertEqual(body["metadata"], '{"k": 1}')  # was silently dropped before 0.4.0
        self.assertEqual(body["title"], "Autumn")
        self.assertEqual(body["compliance_profile"], "both")
        self.assertEqual(body["ai_disclosure"], {"ai_involvement": "generated", "system_name": "Imagine", "system_version": "3.2"})
        self.assertEqual(body["details"], {"license": "CC0", "prompt": "a cat", "private_fields": ["license"]})
        self.assertNotIn("badge", body)

        self.assertEqual(result.watermark_ref, "ref-1")
        self.assertEqual(result.verify_url, "https://verda.ai/abc")
        self.assertEqual(result.private_details_salt, "s4lt")
        self.assertEqual(result.ai_disclosure.system_version, "3.2")
        self.assertEqual(result.ai_disclosure.provider_name, "Acme")  # read back from results
        self.assertEqual(result.ai_disclosure.generated_at, 1793188800)
        self.assertEqual(result.details.prompt, "a cat")

    def test_plain_dicts_work_too(self):
        c = client([FakeResp(200, {"job_id": "j1"})])
        c.encode(url="https://x/a.png", ai_disclosure={"ai_involvement": "altered"}, wait=False)
        self.assertEqual(c._session.calls[0][2]["json"]["ai_disclosure"], {"ai_involvement": "altered"})

    def test_provider_name_cannot_be_passed_or_sent(self):
        with self.assertRaises(TypeError):
            AiDisclosure(provider_name="Acme")
        d = AiDisclosure.from_dict({"provider_name": "Verda Inc.", "ai_involvement": "generated"})
        self.assertEqual(d.provider_name, "Verda Inc.")
        self.assertNotIn("provider_name", d.to_dict())

    def test_assistive_technology_false_is_sent(self):
        self.assertEqual(AiDisclosure(assistive_technology=False).to_dict(), {"assistive_technology": False})


class ComplianceErrors(unittest.TestCase):
    def test_missing_fields_raise_compliance_error(self):
        c = client([FakeResp(400, {
            "response_code": 400, "error_reason": "COMPLIANCE_PROFILE_INCOMPLETE",
            "message": 'compliance profile "us_ca" needs: ai_disclosure.system_name, ai_disclosure.system_version',
            "details": {"profile": "us_ca", "missing": "ai_disclosure.system_name,ai_disclosure.system_version"},
        })])
        with self.assertRaises(ComplianceError) as ctx:
            c.encode(url="https://x/a.png", compliance_profile="us_ca", wait=False)
        self.assertEqual(ctx.exception.missing, ["ai_disclosure.system_name", "ai_disclosure.system_version"])
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.reason, "COMPLIANCE_PROFILE_INCOMPLETE")
        self.assertEqual(ctx.exception.error_code, "")  # unchanged meaning for existing callers

    def test_other_errors_stay_verda_errors(self):
        c = client([FakeResp(500, {"error_reason": "Internal Server Error", "message": "boom"})])
        with self.assertRaises(VerdaError) as ctx:
            c.encode(url="https://x/a.png", wait=False)
        self.assertNotIsInstance(ctx.exception, ComplianceError)


class DecodeResults(unittest.TestCase):
    def test_watermark_ref_and_disclosure_come_back_on_decode(self):
        job = Job.from_dict({
            "job_id": "j2", "job_type": "decode", "status": 3, "match": True, "detected_by": "watermark",
            "provenance": {"watermark_ref": "ref-9", "owner_id": "u1", "verify_url": "https://verda.ai/x"},
            "ai_disclosure": {"ai_involvement": "generated"}, "details": {"license": "CC0"},
        })
        r = DecodeResult.from_job(job.__dict__)
        self.assertEqual(r.watermark_ref, "ref-9")  # was always empty on cloud decodes
        self.assertEqual(r.detected_by, "watermark")
        self.assertEqual(r.ai_disclosure.ai_involvement, "generated")
        self.assertEqual(r.details.license, "CC0")


class RegisterSendsDisclosure(unittest.TestCase):
    def test_register_passes_the_disclosure(self):
        c = client([FakeResp(200, {"uid": 5, "watermark_ref": "r"})])
        c.register_watermark("audio", "abc", ai_disclosure=AiDisclosure(ai_involvement="none"), compliance_profile="eu_art50")
        body = c._session.calls[0][2]["json"]
        self.assertEqual(body["ai_disclosure"], {"ai_involvement": "none"})
        self.assertEqual(body["compliance_profile"], "eu_art50")


if __name__ == "__main__":
    unittest.main()
