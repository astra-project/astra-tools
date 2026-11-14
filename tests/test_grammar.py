"""The forms of a name: an address, a reference with its pin, and an option reference; and of a
recipe's command, a template that `fill` fills in."""

from __future__ import annotations

import pytest

from astra.grammar import (
    Address,
    fill,
    parse_address,
    parse_option_reference,
    parse_reference,
)


def test_an_address_is_its_declarations_then_its_element() -> None:
    """`subanalysis.decision1` is the decision `decision1` of the analysis declared as
    `subanalysis`; `decision1` alone is an element of the analysis itself."""
    address = parse_address("subanalysis.decision1")
    assert (address.declarations, address.id) == (("subanalysis",), "decision1")
    assert parse_address("decision1").declarations == ()
    assert str(address) == "subanalysis.decision1"


def test_a_reference_may_end_in_a_pin() -> None:
    """Elements *reference* and *pin*: `output1#u1`."""
    reference = parse_reference("subanalysis.output1#u1")
    assert (reference.address, reference.pin) == (Address(("subanalysis", "output1")), "u1")
    assert parse_reference("output1").pin is None


def test_the_last_segment_of_an_option_reference_is_the_option() -> None:
    """The option `a` of `subanalysis`'s `decision1` is `subanalysis.decision1.a`."""
    reference = parse_option_reference("subanalysis.decision1.a")
    assert (reference.decision, reference.option) == (Address(("subanalysis", "decision1")), "a")


def test_fill_replaces_each_placeholder_with_what_it_is_given() -> None:
    """Elements *placeholders*: `{inputs.<entry>}`, for an entry as written, dots and `#`
    included, becomes what `inputs` gives for it, `{decisions.<entry>}` what `decisions` gives,
    and `{output}` the output. What a path is written as is the caller's to say: relative or
    absolute, each is put in as given."""
    command = (
        "python make.py '{inputs.input1}' '{inputs.stage.output3#u1}' "
        "--option {decisions.stage.decision2} > '{output}'"
    )
    filled = fill(
        command,
        inputs={"input1": "../data/input1.csv", "stage.output3#u1": "/top/results/u1/x.csv"},
        decisions={"stage.decision2": "b"},
        output="results/u1/output1.json",
    )
    assert filled == (
        "python make.py '../data/input1.csv' '/top/results/u1/x.csv' --option b "
        "> 'results/u1/output1.json'"
    )


def test_fill_gives_inputs_every_entry_in_the_order_given() -> None:
    """`{inputs}` is everything `inputs` gives, in its order, separated by spaces: the order
    of the output's entries, which the caller keeps."""
    inputs = {"second": "b.csv", "first": "a.csv"}
    assert fill("cat {inputs} > {output}", inputs=inputs, decisions={}, output="c.csv") == (
        "cat b.csv a.csv > c.csv"
    )
    assert fill("cat {inputs}", inputs={}, decisions={}, output="c.csv") == "cat "


def test_fill_reads_doubled_braces_as_literal_ones() -> None:
    """`{{` is a literal `{` and `}}` a literal `}`, read from the left."""
    command = "awk '{{print $1}}' {inputs.table} | jq '{{\"n\": .}}' > {output} }}{{"
    filled = fill(command, inputs={"table": "t.csv"}, decisions={}, output="n.json")
    assert filled == "awk '{print $1}' t.csv | jq '{\"n\": .}' > n.json }{"


def test_fill_puts_each_value_in_verbatim_and_reads_none_again() -> None:
    """A value is put in as it is, with no shell quoting, and isn't read as a template: the
    command's own quotes are its author's."""
    filled = fill(
        "run {inputs.data} '{decisions.label}' {output}",
        inputs={"data": "my data.csv"},
        decisions={"label": "it's {output}"},
        output="out {{1}}.json",
    )
    assert filled == "run my data.csv 'it's {output}' out {{1}}.json"


@pytest.mark.parametrize(
    "command", ["{inputs.missing}", "{decisions.missing}", "{decisions}", "{nothing}", "{}"]
)
def test_fill_raises_for_a_placeholder_it_is_given_nothing_for(command: str) -> None:
    """A placeholder that neither mapping gives is a KeyError, as only where the command breaks
    `UNDECLARED_TEMPLATE_REF`, which a valid analysis's doesn't, or the caller leaves an entry
    out."""
    with pytest.raises(KeyError) as raised:
        fill(command, inputs={"data": "d.csv"}, decisions={"label": "a"}, output="o.json")
    assert raised.value.args == (command[1:-1],)  # the placeholder, between its braces


def test_fill_writes_nothing_for_an_entry_that_selects_nothing() -> None:
    """A planned result's `decisions` are given as they are: an entry with no option, as only on
    a stack that breaks a `MUST`, fills in nothing rather than the word `None`."""
    assert fill("run '{decisions.d}'", inputs={}, decisions={"d": None}, output="o") == "run ''"
