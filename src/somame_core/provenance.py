"""Where a value came from, carried with the value.

The central claim of this module is a negative one: there is no member of
:class:`DataOrigin` meaning sample, demo, mock, placeholder or estimate.
Fabricated data has no way to be labelled here, so a system built on these
types has no way to store it and later present it as a measurement.

That only holds if the absence is enforced rather than remembered, so
:func:`check_no_fabrication_member` is a runtime assertion a host program
can call in its own test suite against this enum and its own.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final, Generic, TypeVar

__all__ = [
    "FABRICATION_WORDS",
    "DataOrigin",
    "ProvenanceError",
    "Sourced",
    "Unavailable",
    "check_no_fabrication_member",
]

T = TypeVar("T")


class ProvenanceError(ValueError):
    """A value and its stated origin contradict each other."""


class DataOrigin(enum.Enum):
    """How a value came to be known.

    ``MEASURED``
        Observed by the system itself: a duration it timed, a count of
        rows it wrote, an exit status it saw.
    ``RETRIEVED``
        Read out of a named external system of record.
    ``USER_STATED``
        Supplied by a human who is accountable for it — an internal
        hourly cost, a baseline, a policy threshold.
    ``MODEL_GEN``
        Produced by a language model. Carries no authority. It may be
        shown, but never as a measurement and never as a baseline.
    ``UNAVAILABLE``
        Not known. The only origin that may carry no value, and the
        reason it is a first-class origin rather than ``None``: "we do
        not know" is information, and it deserves somewhere to live
        alongside why.
    """

    MEASURED = "measured"
    RETRIEVED = "retrieved"
    USER_STATED = "user_stated"
    MODEL_GEN = "model_gen"
    UNAVAILABLE = "unavailable"

    @property
    def is_evidence(self) -> bool:
        """True when a value of this origin may back a reported figure.

        A model's own output is not evidence about the world, so it is
        excluded here even though it is a perfectly legitimate thing to
        store and display as what it is.
        """
        return self in (DataOrigin.MEASURED, DataOrigin.RETRIEVED, DataOrigin.USER_STATED)


#: Words that, appearing in an origin's name, would reopen the door this
#: module exists to keep shut.
FABRICATION_WORDS: Final[frozenset[str]] = frozenset(
    {"sample", "demo", "mock", "fake", "placeholder", "dummy", "stub", "synthetic", "example", "estimated"}
)


def check_no_fabrication_member(enum_cls: type[enum.Enum] = DataOrigin) -> None:
    """Raise if ``enum_cls`` has gained a way to label invented data.

    Call this from a host project's own tests, against this enum and
    against any enum of its own that plays the same role. A convention
    that lives only in a code review is one commit from gone.
    """
    for member in enum_cls:
        name = member.name.lower()
        value = str(member.value).lower()
        for word in FABRICATION_WORDS:
            if word in name or word in value:
                raise ProvenanceError(
                    f"{enum_cls.__name__}.{member.name} introduces a label for fabricated data "
                    f"({word!r}). Fabricated data must have no way to be stored as though measured."
                )


@dataclass(frozen=True, slots=True)
class Sourced(Generic[T]):
    """A value together with where it came from.

    Two rules are enforced at construction, because a check that runs
    only at the point of display runs too late:

    * An ``UNAVAILABLE`` value must be ``None``. There is no such thing
      as a number we do not have.
    * Any other origin must carry a value, and must name its source.

    ``source`` is a free-text identifier of the system, person or
    measurement that produced the value — "netsuite:gl.2026-09",
    "director:hourly_cost", "timer:task_duration". It is required
    because "retrieved" without saying from where is not provenance.
    """

    value: T | None
    origin: DataOrigin
    source: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.origin is DataOrigin.UNAVAILABLE:
            if self.value is not None:
                raise ProvenanceError(
                    "A value whose origin is UNAVAILABLE cannot carry a value. "
                    "If the value is known, give it the origin it actually has."
                )
            if not self.reason:
                raise ProvenanceError(
                    "An UNAVAILABLE value must carry a reason. "
                    "A blank with no explanation is indistinguishable from a bug."
                )
            return

        if self.value is None:
            raise ProvenanceError(
                f"Origin {self.origin.name} promises a value, but none was given. "
                "Use DataOrigin.UNAVAILABLE with a reason instead."
            )
        if not self.source:
            raise ProvenanceError(
                f"Origin {self.origin.name} requires a named source. "
                "'Retrieved' without saying from where is not provenance."
            )

    @property
    def known(self) -> bool:
        return self.origin is not DataOrigin.UNAVAILABLE

    @property
    def is_evidence(self) -> bool:
        """Whether this may be used to back a reported figure."""
        return self.origin.is_evidence

    def require(self) -> T:
        """Return the value, or raise if it is not known.

        For call sites that genuinely cannot proceed without it. Prefer
        rendering the absence to the person over raising.
        """
        if self.value is None:
            raise ProvenanceError(self.reason or "Value is unavailable.")
        return self.value

    def unwrap_or(self, default: T) -> T:
        """Return the value, or ``default``.

        Deliberately awkward to reach for: substituting a default is how
        an unknown quietly becomes a zero on someone's dashboard. It
        exists for genuine defaults (a page size, a retry count), not
        for reported figures.
        """
        return default if self.value is None else self.value

    def __str__(self) -> str:
        if not self.known:
            return f"unavailable ({self.reason})"
        return f"{self.value} ({self.origin.value} · {self.source})"


def Unavailable(reason: str) -> Sourced[T]:
    """A :class:`Sourced` holding nothing, and saying why."""
    return Sourced(value=None, origin=DataOrigin.UNAVAILABLE, reason=reason)
