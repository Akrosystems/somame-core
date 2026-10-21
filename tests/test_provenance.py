"""The Zero-Fake-Data Law, as assertions."""

from __future__ import annotations

import dataclasses

import pytest

from somame_core.provenance import (
    FABRICATION_WORDS,
    DataOrigin,
    ProvenanceError,
    Sourced,
    Unavailable,
    check_no_fabrication_member,
)


def test_no_origin_can_label_fabricated_data():
    check_no_fabrication_member()


def test_the_check_catches_a_reintroduced_member():
    """Proves the guard works, rather than trusting that it does."""
    import enum

    class Slipped(enum.Enum):
        MEASURED = "measured"
        SAMPLE = "sample"

    with pytest.raises(ProvenanceError, match="sample"):
        check_no_fabrication_member(Slipped)


@pytest.mark.parametrize("word", sorted(FABRICATION_WORDS))
def test_no_origin_name_or_value_contains_a_fabrication_word(word):
    for member in DataOrigin:
        assert word not in member.name.lower()
        assert word not in str(member.value).lower()


def test_unavailable_cannot_carry_a_value():
    with pytest.raises(ProvenanceError, match="cannot carry a value"):
        Sourced(42.0, DataOrigin.UNAVAILABLE, reason="nope")


def test_unavailable_must_say_why():
    with pytest.raises(ProvenanceError, match="must carry a reason"):
        Sourced(None, DataOrigin.UNAVAILABLE)


def test_a_known_origin_must_carry_a_value():
    with pytest.raises(ProvenanceError, match="promises a value"):
        Sourced(None, DataOrigin.MEASURED, source="timer:x")


def test_a_known_origin_must_name_its_source():
    with pytest.raises(ProvenanceError, match="named source"):
        Sourced(1.0, DataOrigin.RETRIEVED)


def test_model_output_is_not_evidence():
    """A model's guess may be stored and shown. It may not back a figure."""
    guess = Sourced(3600.0, DataOrigin.MODEL_GEN, source="model:estimate")
    assert guess.known
    assert not guess.is_evidence


def test_measured_retrieved_and_stated_are_evidence():
    for origin, src in (
        (DataOrigin.MEASURED, "timer:task"),
        (DataOrigin.RETRIEVED, "netsuite:gl"),
        (DataOrigin.USER_STATED, "director:rate"),
    ):
        assert Sourced(1.0, origin, source=src).is_evidence


def test_require_raises_with_the_reason():
    u = Unavailable("No baseline is on record.")
    with pytest.raises(ProvenanceError, match="No baseline is on record."):
        u.require()


def test_str_of_an_unknown_explains_itself():
    assert str(Unavailable("nobody stated a rate")) == "unavailable (nobody stated a rate)"


def test_sourced_is_frozen():
    """Provenance that can be edited after the fact is not provenance."""
    s = Sourced(1.0, DataOrigin.MEASURED, source="timer:x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.value = 2.0  # type: ignore[misc]
