"""Unit-проверки пробного письма; реальный SES не вызывается."""

import re
import unittest
from email import message_from_bytes
from email.policy import default
from unittest.mock import patch

from scripts import send_test_verification_email as script


class TestEditableEmail(unittest.TestCase):
    def test_five_variants_preserve_codes_and_expected_differences(self):
        settings = script.MailSettings("us-east-1", "sender@example.com", "ALXPRGS")
        messages = {
            variant: message_from_bytes(
                script.build_test_message(
                    "recipient@example.com",
                    settings,
                    variant=variant,
                    code="000042",
                    batch_id="unit",
                ).as_bytes(),
                policy=default,
            )
            for variant in script.VARIANTS
        }
        for variant, message in messages.items():
            with self.subTest(variant=variant):
                self.assertIn(f"OTP test {variant} unit", message["Subject"])
                self.assertIn("000042", message.get_body(preferencelist=("html",)).get_content())
        self.assertEqual(messages[1].get_content_type(), "multipart/alternative")
        self.assertEqual(messages[5].get_content_type(), "text/html")
        self.assertIsNone(messages[5].get_body(preferencelist=("plain",)))
        self.assertEqual(
            messages[1].get_body(preferencelist=("html",)).get_content(),
            messages[2].get_body(preferencelist=("html",)).get_content(),
        )
        for part in messages[2].iter_parts():
            self.assertIn("000042", part.get_payload())
            self.assertEqual(part["Content-Transfer-Encoding"], "quoted-printable")
        self.assertTrue(messages[3]["Subject"].startswith("000042 is your"))
        self.assertTrue(
            messages[4]
            .get_body(preferencelist=("plain",))
            .get_content()
            .startswith("Your verification code is: 000042")
        )

    def test_all_variants_send_five_independent_messages(self):
        with patch.object(script, "send_ses_email", return_value="unit-message") as send:
            self.assertEqual(script.main(["--to", "recipient@example.com", "--all-variants"]), 0)
        self.assertEqual(send.call_count, 5)
        codes = set()
        for call in send.call_args_list:
            message = message_from_bytes(call.kwargs["raw_message"], policy=default)
            codes.add(
                re.search(
                    r"verification code is: (\d{6})",
                    message.get_body(preferencelist=("html",)).get_content(),
                )[1]
            )
        self.assertEqual(len(codes), 5)

    def test_all_variants_dry_run_never_sends(self):
        with patch.object(script, "send_ses_email") as send:
            self.assertEqual(
                script.main(["--to", "recipient@example.com", "--all-variants", "--dry-run"]), 0
            )
        send.assert_not_called()

    def test_batch_stops_after_first_failed_send(self):
        with patch.object(
            script,
            "send_ses_email",
            side_effect=["unit-message", script.SESEmailDeliveryError("throttled")],
        ) as send:
            self.assertEqual(script.main(["--to", "recipient@example.com", "--all-variants"]), 1)
        self.assertEqual(send.call_count, 2)

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
