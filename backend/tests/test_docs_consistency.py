"""The documented ER diagrams must describe the implemented schema exactly."""

import re
from pathlib import Path

from app.models import Base

DATA_MODEL = Path(__file__).resolve().parents[2] / "docs" / "data-model.md"


def _diagrams() -> list[str]:
    text = DATA_MODEL.read_text(encoding="utf-8")
    return [block.split("```")[0] for block in text.split("```mermaid")[1:]]


def test_every_table_and_column_is_in_the_er_diagrams():
    entities = {}
    for block in _diagrams():
        for name, body in re.findall(r"(\w+) \{(.*?)\}", block, re.S):
            entities[name.lower()] = [line.split()[1] for line in body.strip().splitlines()]
    assert set(entities) == set(Base.metadata.tables)
    for table in Base.metadata.sorted_tables:
        assert entities[table.name] == [column.name for column in table.columns], table.name


def test_every_foreign_key_is_an_edge_in_the_er_diagrams():
    edges = set()
    for block in _diagrams():
        edges |= {
            (b.lower(), a.lower()) for a, b in re.findall(r"^\s*(\w+) \S+ (\w+) :", block, re.M)
        }
    foreign_keys = {
        (fk.parent.table.name, fk.column.table.name)
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
    }
    assert foreign_keys == edges
