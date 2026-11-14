"""The forms of a name, parse and format, and of a recipe's command, which `fill` fills in.

```abnf
id               = lower *( lower / DIGIT / "_" )
address          = id *( "." id )               ; [declaration "."]... element
reference        = address [ "#" id ]           ; "#" pins a universe
option-reference = address "." id              ; a decision's address, then an option id
```

Binding parses only what the schema accepted, which takes its form (`INVALID_REFERENCE`), so a
value is parsed by splitting it. An address formats as it is written, through `str()`.

A command is a template (Elements *placeholders*): read from the left, `{{` is a literal `{`,
`}}` a literal `}`, and any other `{` opens a placeholder, which ends at the next `}`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Address:
    """Ids joined by `.`: the ids of the declarations that lead to an element, then its own."""

    segments: tuple[str, ...]

    @property
    def declarations(self) -> tuple[str, ...]:
        """Every segment but the last: the ids of the declarations the address goes through."""
        return self.segments[:-1]

    @property
    def id(self) -> str:
        """The last segment: the id of the element in the analysis reached."""
        return self.segments[-1]

    def __str__(self) -> str:
        return ".".join(self.segments)


@dataclass(frozen=True)
class Reference:
    """An address, which may be followed by a pin, `#` and a universe's id."""

    address: Address
    pin: str | None = None


@dataclass(frozen=True)
class OptionReference:
    """A decision's address, `.`, then an option's id: the last segment is always the option."""

    decision: Address
    option: str


def parse_address(text: str) -> Address:
    return Address(tuple(text.split(".")))


def parse_reference(text: str) -> Reference:
    address, hash_, pin = text.partition("#")
    return Reference(parse_address(address), pin if hash_ else None)


def parse_option_reference(text: str) -> OptionReference:
    address = parse_address(text)
    return OptionReference(Address(address.declarations), address.id)


TEMPLATE = re.compile(r"\{\{|\}\}|\{([^}]*)\}")
"""What a command holds, read from the left: `{{`, `}}`, or a placeholder up to the next `}`.
A valid stack's commands hold nothing else (`UNDECLARED_TEMPLATE_REF`)."""


def fill(
    command: str, *, inputs: Mapping[str, str], decisions: Mapping[str, str | None], output: str
) -> str:
    """`command` with each `{{` and `}}` replaced by one brace, and each placeholder replaced
    verbatim, with no shell quoting: `{inputs.<entry>}` by what `inputs` gives for the entry,
    `{decisions.<entry>}` by what `decisions` gives for it, `{inputs}` by everything `inputs`
    gives, in its order, separated by spaces, and `{output}` by `output`.

    The grammar alone: what a path is written as, relative to the folder the recipe runs in or
    absolute, in which checkout, is the caller's to say. A runner gives, for each entry of the
    output's `inputs` in their order, the path it has what the entry reads at, the option each
    entry of its `decisions` selects, as a planned result gives them, and the path the recipe
    writes its result to. An entry that selects nothing, as only on a stack that breaks a
    `MUST`, fills in nothing. Raises KeyError, naming the placeholder, for one neither gives, as
    only where the command breaks `UNDECLARED_TEMPLATE_REF` or an entry is left out."""

    def filled(match: re.Match[str]) -> str:
        text, placeholder = match[0], match[1]
        if placeholder is None:
            return text[0]
        if placeholder == "output":
            return output
        if placeholder == "inputs":
            return " ".join(inputs.values())
        field, _, entry = placeholder.partition(".")
        given = {"inputs": inputs, "decisions": decisions}.get(field)
        if given is None or entry not in given:
            raise KeyError(placeholder)
        return given[entry] or ""

    return TEMPLATE.sub(filled, command)
