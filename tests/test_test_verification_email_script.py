"""Unit-проверки пробного письма; реальный SES не вызывается."""

import unittest
from unittest.mock import patch

from scripts import send_test_verification_email as script


class TestEditableEmail(unittest.TestCase):
    def test_leading_zero_code_and_editable_templates(self):
        settings = script.MailSettings("us-east-1", "sender@example.com", "ALXPRGS")
        with (
            patch.object(script.secrets, "randbelow", return_value=42),
            patch.object(script, "SUBJECT", "Edited subject"),
            patch.object(script, "TEXT_TEMPLATE", "Edited text {code}"),
            patch.object(script, "HTML_TEMPLATE", "<p>Edited HTML {code}</p>"),
        ):
            message = script.build_test_message("recipient@example.com", settings)
        self.assertEqual(message["Subject"], "Edited subject")
        self.assertIn(
            "Edited text 000042", message.get_body(preferencelist=("plain",)).get_content()
        )
        self.assertIn(
            "Edited HTML 000042", message.get_body(preferencelist=("html",)).get_content()
        )

    def test_dry_run_does_not_send(self):
        with patch.object(script, "send_ses_email") as send:
            self.assertEqual(script.main(["--to", "recipient@example.com", "--dry-run"]), 0)
        send.assert_not_called()

    def test_real_mode_submits_raw_multipart_to_ses(self):
        with patch.object(script, "send_ses_email", return_value="unit-message") as send:
            self.assertEqual(script.main(["--to", "recipient@example.com"]), 0)
        self.assertEqual(send.call_args.kwargs["to_email"], "recipient@example.com")
        self.assertIn(b"multipart/alternative", send.call_args.kwargs["raw_message"])

    def test_header_injection_and_multiple_recipients_are_rejected(self):
        for address in ("a@example.com\r\nBcc: b@example.com", "a@example.com,b@example.com"):
            with self.subTest(address=address), patch.object(script, "send_ses_email") as send:
                self.assertEqual(script.main(["--to", address]), 1)
                send.assert_not_called()

    def test_delivery_failure_returns_nonzero(self):
        with patch.object(
            script, "send_ses_email", side_effect=script.SESEmailDeliveryError("access_denied")
        ):
            self.assertEqual(script.main(["--to", "recipient@example.com"]), 1)


if __name__ == "__main__":
    unittest.main()
