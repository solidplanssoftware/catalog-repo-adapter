from __future__ import annotations

from schema import SchemaDefinition, SchemaDocument, SchemaMetadata, Version


def test_type_schema_models_remain_available() -> None:
    document = SchemaDocument(
        metadata=SchemaMetadata(
            schemaVersion=Version(major=0), version=Version(major=0)
        ),
        externalSchemas={},
        definitions={
            "user": SchemaDefinition(
                name="user",
                fields={},
            )
        },
    )

    assert document.metadata.schemaVersion == Version(major=0, minor=0)
    assert document.metadata.version == Version(major=0, minor=0)
    assert "user" in document.definitions
