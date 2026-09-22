from pathlib import Path
from uuid import uuid4

from app.core.exceptions import AppError
from app.services.report_storage import PrivateReportStorage


def test_private_report_storage_checks_signature_and_keeps_paths_scoped(tmp_path: Path) -> None:
    storage = PrivateReportStorage(tmp_path, max_bytes=1024)
    reporter_id, report_id = uuid4(), uuid4()
    stored = storage.save(
        reporter_id=reporter_id,
        report_id=report_id,
        filename="../../evidence.png",
        declared_media_type="image/png",
        content=b"\x89PNG\r\n\x1a\ncontent",
    )

    assert storage.resolve(stored.key).is_file()
    assert storage.resolve(stored.key).is_relative_to(tmp_path.resolve())
    assert stored.original_filename == "evidence.png"


def test_private_report_storage_rejects_declared_type_mismatch(tmp_path: Path) -> None:
    storage = PrivateReportStorage(tmp_path, max_bytes=1024)
    try:
        storage.save(
            reporter_id=uuid4(),
            report_id=uuid4(),
            filename="fake.pdf",
            declared_media_type="application/pdf",
            content=b"\x89PNG\r\n\x1a\ncontent",
        )
    except AppError as raised:
        assert raised.code == "report_evidence_type_invalid"
    else:
        raise AssertionError("mismatched evidence must be rejected")
