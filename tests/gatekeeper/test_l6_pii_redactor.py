"""L6 PII redaction, including the ordering invariant."""

from __future__ import annotations

import pytest

from services.agent1_gatekeeper.pipeline.l6_pii_redactor import luhn_valid, redact
from shared.contracts.enums import ReasonCode


def test_email_is_redacted():
    result = redact("email me at john.doe@example.com about the program")
    assert "john.doe@example.com" not in result.text
    assert "<EMAIL_1>" in result.text


def test_phone_is_redacted():
    result = redact("call me on +94 77 123 4567 to discuss")
    assert "77 123 4567" not in result.text
    assert "<PHONE_1>" in result.text


def test_sri_lankan_nic_old_format():
    result = redact("my NIC is 921234567V for the membership")
    assert "921234567V" not in result.text
    assert "<NIC_1>" in result.text


def test_sri_lankan_nic_new_format():
    result = redact("new NIC 199212345678 here")
    assert "199212345678" not in result.text


def test_passport_is_redacted():
    result = redact("passport N1234567 for the competition")
    assert "N1234567" not in result.text


def test_valid_card_is_redacted():
    result = redact("card 4532015112830366 for the subscription")
    assert "4532015112830366" not in result.text
    assert "<CARD_1>" in result.text


def test_card_redaction_preserves_surrounding_spacing():
    result = redact("card 4532015112830366 for the subscription")
    assert "<CARD_1> for" in result.text


def test_spaced_card_format_is_redacted():
    result = redact("card 4532 0151 1283 0366 here")
    assert "4532 0151 1283 0366" not in result.text


# --- False positives: the reason Luhn is used ------------------------------


def test_workout_numbers_are_not_redacted():
    """Gym text is full of digit runs. Redacting one corrupts a log."""
    text = "did 3x5 at 100kg then 5x5 at 120kg on 2026-01-15"
    result = redact(text)
    assert result.text == text
    assert not result.contains_pii


def test_a_digit_run_failing_luhn_is_not_a_card():
    result = redact("reference number 1234567890123456 for the order")
    assert not any(f.kind == "CARD" for f in result.findings)


@pytest.mark.parametrize(
    "number,expected",
    [
        ("4532015112830366", True),
        ("5425233430109903", True),
        ("4532015112830367", False),
        ("1234567890123456", False),
    ],
)
def test_luhn_checksum(number, expected):
    assert luhn_valid(number) is expected


def test_luhn_rejects_short_numbers():
    assert luhn_valid("123") is False


# --- Vault and rehydration --------------------------------------------------


def test_placeholders_are_stable_within_a_request():
    result = redact("write to a@b.com and c@d.com")
    placeholders = [f.placeholder for f in result.findings]
    assert placeholders == ["<EMAIL_1>", "<EMAIL_2>"]


def test_rehydration_restores_the_original():
    original = "contact jane@gym.lk or +94112345678"
    result = redact(original)
    assert result.rehydrate(result.text) == original


def test_multiple_pii_types_in_one_message():
    result = redact("contact jane@gym.lk or +94112345678, NIC 902345678X")
    kinds = {f.kind for f in result.findings}
    assert kinds == {"EMAIL", "PHONE", "NIC"}


# --- Trace and privacy ------------------------------------------------------


def test_the_trace_does_not_record_the_original_value():
    """Traces are logged and persisted, so storing the value would defeat the
    redaction it is recording."""
    result = redact("email me at secret.person@example.com")
    serialised = str(result.trace.to_dict())
    assert "secret.person@example.com" not in serialised


def test_reason_codes_are_raised_when_pii_is_found():
    result = redact("email me at a@b.com")
    assert ReasonCode.PII_DETECTED in result.trace.reason_codes
    assert ReasonCode.PII_REDACTED in result.trace.reason_codes


def test_clean_text_raises_no_reason_codes():
    assert redact("squatted 100kg for 5 reps").trace.reason_codes == []


def test_empty_input_is_safe():
    result = redact("")
    assert result.text == ""
    assert not result.contains_pii
