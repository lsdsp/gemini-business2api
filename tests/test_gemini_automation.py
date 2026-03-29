import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

fake_config = SimpleNamespace(
    basic=SimpleNamespace(auth_use_url_submit=True),
    retry=SimpleNamespace(verification_code_resend_count=2),
    automation_selectors=None,
)

sys.modules.setdefault("core.config", types.SimpleNamespace(config=fake_config))
sys.modules.setdefault(
    "DrissionPage",
    types.SimpleNamespace(ChromiumPage=object, ChromiumOptions=object),
)
sys.modules.setdefault(
    "core.base_task_service",
    types.SimpleNamespace(TaskCancelledError=type("TaskCancelledError", (Exception,), {})),
)

from core.gemini_automation import GeminiAutomation


class SequencedUrlPage:
    def __init__(self, urls):
        self._urls = list(urls)
        self._index = 0

    @property
    def url(self):
        if not self._urls:
            return ""
        value = self._urls[min(self._index, len(self._urls) - 1)]
        if self._index < len(self._urls) - 1:
            self._index += 1
        return value


class FakeInput:
    def __init__(self):
        self.values = []
        self.clicked = 0

    def click(self):
        self.clicked += 1

    def input(self, value, clear=False):
        self.values.append((value, clear))


class FakeButton:
    def __init__(self):
        self.clicked = 0

    def click(self):
        self.clicked += 1


class GeminiAutomationTests(unittest.TestCase):
    def setUp(self):
        self.automation = GeminiAutomation(headless=True)

    def test_new_account_always_uses_page_input_submission(self):
        with patch.object(fake_config.basic, "auth_use_url_submit", True):
            self.assertFalse(self.automation._should_use_url_submit(is_new_account=True))
            self.assertTrue(self.automation._should_use_url_submit(is_new_account=False))

    @patch("core.gemini_automation.time.sleep", return_value=None)
    def test_wait_for_post_email_step_detects_verify_page(self, _sleep):
        page = SequencedUrlPage([
            "https://auth.business.gemini.google/login",
            "https://auth.business.gemini.google/verify-oob-code",
        ])

        result = self.automation._wait_for_post_email_step(page, timeout=2)

        self.assertEqual(result, "verify-oob-code")

    @patch("core.gemini_automation.time.sleep", return_value=None)
    def test_wait_for_post_email_step_detects_signin_error(self, _sleep):
        page = SequencedUrlPage([
            "https://auth.business.gemini.google/login",
            "https://auth.business.gemini.google/signin-error",
        ])

        result = self.automation._wait_for_post_email_step(page, timeout=2)

        self.assertEqual(result, "signin-error")

    def test_poll_for_code_clicks_resend_after_initial_timeout(self):
        mail_client = SimpleNamespace()
        mail_client.poll_for_code_calls = []

        def poll_for_code(timeout, interval, since_time):
            mail_client.poll_for_code_calls.append((timeout, interval, since_time))
            return None if len(mail_client.poll_for_code_calls) == 1 else "654321"

        mail_client.poll_for_code = poll_for_code

        with patch.object(fake_config.retry, "verification_code_resend_count", 1):
            with patch.object(self.automation, "_click_resend_code_button", return_value=True) as resend_mock:
                code = self.automation._poll_for_verification_code(
                    page=SimpleNamespace(),
                    mail_client=mail_client,
                    poll_since_time="since-time",
                )

        self.assertEqual(code, "654321")
        self.assertEqual(resend_mock.call_count, 1)
        self.assertEqual(len(mail_client.poll_for_code_calls), 2)

    @patch("core.gemini_automation.time.sleep", return_value=None)
    def test_submit_verification_code_clicks_verify_button(self, _sleep):
        code_input = FakeInput()
        verify_button = FakeButton()

        with patch.object(self.automation, "_find_code_input", return_value=code_input):
            with patch.object(self.automation, "_find_verify_button", return_value=verify_button):
                submitted = self.automation._submit_verification_code(
                    page=SimpleNamespace(url="https://auth.business.gemini.google/verify-oob-code"),
                    code="123456",
                )

        self.assertTrue(submitted)
        self.assertIn(("123456", True), code_input.values)
        self.assertEqual(verify_button.clicked, 1)


if __name__ == "__main__":
    unittest.main()
