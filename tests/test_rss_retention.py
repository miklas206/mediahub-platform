import pytest
from mediahub.rss_retention import RetentionRule, reached


def torrent(**changes):
    return (
        dict(progress=1, size=100_000_000, uploaded=200_000_000, seeding_time=48 * 3600) | changes
    )


def test_disabled_by_default_and_ratio_is_uploaded_over_file_size():
    assert not reached(RetentionRule(), torrent())
    rule = RetentionRule(mode="ratio", uploadRatio=2)
    assert reached(rule, torrent())
    assert not reached(rule, torrent(uploaded=199_999_999))
    # Imported/rechecked files may have downloaded=0 and a misleading qBittorrent ratio.
    assert not reached(rule, torrent(uploaded=1, downloaded=0, ratio=9999))


def test_disabled_add_payload_stays_compatible_and_enabled_rule_is_forwarded():
    from mediahub.apps.seedbox_daily import AddTorrent

    request = AddTorrent(magnet="magnet:?xt=urn:btih:" + "a" * 40, storageId="downloads")
    assert "retention" not in request.private_payload()
    request.retention = RetentionRule(mode="ratio", action="delete_files")
    assert request.private_payload()["retention"]["action"] == "delete_files"


def test_time_uses_actual_seeding_seconds_and_requires_completion():
    rule = RetentionRule(mode="time", seedHours=48)
    assert reached(rule, torrent())
    assert not reached(rule, torrent(seeding_time=48 * 3600 - 1))
    assert not reached(rule, torrent(progress=0.9))


def test_both_and_either_rules():
    assert reached(RetentionRule(mode="both"), torrent())
    assert not reached(RetentionRule(mode="both"), torrent(uploaded=0))
    assert reached(RetentionRule(mode="either"), torrent(uploaded=0))
    assert not reached(RetentionRule(mode="either"), torrent(uploaded=0, seeding_time=0))


@pytest.mark.parametrize(
    "change", [{"size": 0}, {"uploaded": None}, {"seeding_time": -1}, {"progress": float("nan")}]
)
def test_invalid_measurements_never_trigger_cleanup(change):
    assert not reached(RetentionRule(mode="either"), torrent(**change))
