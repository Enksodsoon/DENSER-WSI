from dataclasses import dataclass

from scripts.create_private_freeze import freeze_json_document


@dataclass(frozen=True)
class _TupleRecord:
    dependency_versions: tuple[tuple[str, str], ...]


def test_freeze_schema_document_uses_json_arrays_for_tuple_fields() -> None:
    document = freeze_json_document(
        _TupleRecord((('python', '3.12.13'),))  # type: ignore[arg-type]
    )
    assert document == {"dependency_versions": [["python", "3.12.13"]]}
