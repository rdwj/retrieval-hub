"""Tests for eval-driven self-improvement."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from retrieval_hub.ontology.self_improve import (
    SCORE_CEILING,
    SCORE_FLOOR,
    MappingFinding,
    ScoreAdjustment,
    adjust_authority_scores,
    apply_adjustments,
    evaluate_mapping_quality,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mapping(
    id, canonical_name, source_slug, local_name="Default", authority_score=1.0,
):
    return SimpleNamespace(
        id=id,
        canonical_name=canonical_name,
        source_slug=source_slug,
        local_name=local_name,
        authority_score=authority_score,
    )


def _mock_session_with_mappings(mapping_rows):
    """Build a mock session whose query(OntologyMapping).all() returns mapping_rows."""
    session = MagicMock()
    query = MagicMock()
    query.all.return_value = mapping_rows
    session.query.return_value = query
    return session


def _make_quality_entry(
    canonical_name,
    source_slug,
    total_hits=0,
    precision=0.0,
    is_dead=False,
):
    """Build a per_mapping_quality dict entry."""
    return {
        "canonical_name": canonical_name,
        "source_slug": source_slug,
        "local_names": [],
        "queries_exercised": 1,
        "total_hits": total_hits,
        "total_in_top_k": total_hits,
        "precision": precision,
        "is_dead": is_dead,
        "mean_authority_score": 0.8,
    }


def _make_finding(
    mapping_id=1,
    canonical_name="Condition",
    source_slug="src-a",
    local_name="Default",
    category="healthy",
    authority_score=0.9,
    precision=0.6,
):
    """Build a MappingFinding for adjust_authority_scores tests."""
    return MappingFinding(
        mapping_id=mapping_id,
        canonical_name=canonical_name,
        source_slug=source_slug,
        local_name=local_name,
        category=category,
        authority_score=authority_score,
        metrics={"precision": precision},
    )


# ---------------------------------------------------------------------------
# evaluate_mapping_quality
# ---------------------------------------------------------------------------


class TestEvaluateMappingQuality:
    def test_evaluate_healthy_mapping(self):
        """Mapping with hits and decent precision is classified as healthy."""
        mapping = _make_mapping(1, "Condition", "src-a", "Hypertension", 0.8)
        session = _mock_session_with_mappings([mapping])

        quality = {
            "Condition||src-a": _make_quality_entry(
                "Condition", "src-a", total_hits=5, precision=0.6, is_dead=False,
            ),
        }

        findings = evaluate_mapping_quality(session, quality)
        assert len(findings) == 1
        assert findings[0].category == "healthy"
        assert findings[0].mapping_id == 1

    def test_evaluate_dead_mapping(self):
        """Mapping flagged as dead is classified as dead."""
        mapping = _make_mapping(1, "Condition", "src-a", "Hypertension", 0.8)
        session = _mock_session_with_mappings([mapping])

        quality = {
            "Condition||src-a": _make_quality_entry(
                "Condition", "src-a", total_hits=0, precision=0.0, is_dead=True,
            ),
        }

        findings = evaluate_mapping_quality(session, quality)
        assert len(findings) == 1
        assert findings[0].category == "dead"

    def test_evaluate_underperforming(self):
        """Mapping with hits but low precision is classified as underperforming."""
        mapping = _make_mapping(1, "Condition", "src-a", "Hypertension", 0.8)
        session = _mock_session_with_mappings([mapping])

        quality = {
            "Condition||src-a": _make_quality_entry(
                "Condition", "src-a", total_hits=5, precision=0.1, is_dead=False,
            ),
        }

        findings = evaluate_mapping_quality(session, quality)
        assert len(findings) == 1
        assert findings[0].category == "underperforming"

    def test_evaluate_missing_coverage(self):
        """Source with mapping for a concept but not exercised gets missing_coverage."""
        mapping_a = _make_mapping(1, "Condition", "a", "Hypertension", 0.8)
        mapping_b = _make_mapping(2, "Condition", "b", "BloodPressure", 0.7)
        session = _mock_session_with_mappings([mapping_a, mapping_b])

        # Only source "a" is exercised; source "b" is not in per_mapping_quality.
        quality = {
            "Condition||a": _make_quality_entry(
                "Condition", "a", total_hits=5, precision=0.6,
            ),
        }

        findings = evaluate_mapping_quality(session, quality)
        exercised = [f for f in findings if f.source_slug == "a"]
        missing = [f for f in findings if f.source_slug == "b"]

        assert len(exercised) == 1
        assert exercised[0].category == "healthy"
        assert len(missing) == 1
        assert missing[0].category == "missing_coverage"
        assert missing[0].mapping_id == 2

    def test_evaluate_no_matching_rows(self):
        """Quality entry with no matching DB mapping produces no finding."""
        # DB has no mappings for the concept/source in the quality data.
        session = _mock_session_with_mappings([])

        quality = {
            "Condition||src-a": _make_quality_entry(
                "Condition", "src-a", total_hits=5, precision=0.6,
            ),
        }

        findings = evaluate_mapping_quality(session, quality)
        assert findings == []


# ---------------------------------------------------------------------------
# adjust_authority_scores
# ---------------------------------------------------------------------------


class TestAdjustAuthorityScores:
    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_healthy_boost(self, mock_compute):
        """Healthy mapping with high precision gets a 1.05x boost."""
        mock_compute.return_value = [(1, 0.9)]
        finding = _make_finding(
            mapping_id=1, category="healthy", authority_score=0.9, precision=0.6,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert len(adjustments) == 1
        assert adjustments[0].new_score == 0.945
        assert adjustments[0].old_score == 0.9

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_dead_damp(self, mock_compute):
        """Dead mapping gets a 0.8x damping factor."""
        mock_compute.return_value = [(1, 0.9)]
        finding = _make_finding(
            mapping_id=1, category="dead", authority_score=0.9,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert len(adjustments) == 1
        assert adjustments[0].new_score == 0.72

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_underperforming_damp(self, mock_compute):
        """Underperforming mapping gets a 0.9x damping factor."""
        mock_compute.return_value = [(1, 0.9)]
        finding = _make_finding(
            mapping_id=1, category="underperforming", authority_score=0.9,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert len(adjustments) == 1
        assert adjustments[0].new_score == 0.81

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_score_floor(self, mock_compute):
        """Score below SCORE_FLOOR is clamped to 0.3."""
        mock_compute.return_value = [(1, 0.35)]
        finding = _make_finding(
            mapping_id=1, category="dead", authority_score=0.35,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert len(adjustments) == 1
        # raw = 0.35 * 0.8 = 0.28, clamped to 0.3
        assert adjustments[0].new_score == SCORE_FLOOR

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_score_ceiling(self, mock_compute):
        """Score above SCORE_CEILING is clamped to 1.0."""
        mock_compute.return_value = [(1, 0.98)]
        finding = _make_finding(
            mapping_id=1, category="healthy", authority_score=0.98, precision=0.6,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert len(adjustments) == 1
        # raw = 0.98 * 1.05 = 1.029, clamped to 1.0
        assert adjustments[0].new_score == SCORE_CEILING

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_idempotency(self, mock_compute):
        """Running adjust twice with same findings produces identical results."""
        mock_compute.return_value = [(1, 0.9)]
        finding = _make_finding(
            mapping_id=1, category="dead", authority_score=0.9,
        )

        session = MagicMock()
        first = adjust_authority_scores(session, [finding])
        second = adjust_authority_scores(session, [finding])

        assert len(first) == len(second)
        assert first[0].new_score == second[0].new_score

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_no_change_skipped(self, mock_compute):
        """When new_score equals current authority_score, no adjustment is created."""
        # base=0.9, category="healthy", precision=0.4 (< PRECISION_BOOST_THRESHOLD)
        # eval_factor=1.0, raw=0.9, new_score=0.9 == authority_score → skip
        mock_compute.return_value = [(1, 0.9)]
        finding = _make_finding(
            mapping_id=1,
            category="healthy",
            authority_score=0.9,
            precision=0.4,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert adjustments == []

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_missing_coverage_no_change(self, mock_compute):
        """missing_coverage uses eval_factor=1.0, so base == current means no change."""
        mock_compute.return_value = [(1, 0.8)]
        finding = _make_finding(
            mapping_id=1,
            category="missing_coverage",
            authority_score=0.8,
        )

        adjustments = adjust_authority_scores(MagicMock(), [finding])

        assert adjustments == []


# ---------------------------------------------------------------------------
# apply_adjustments
# ---------------------------------------------------------------------------


class TestApplyAdjustments:
    def test_apply_adjustments(self):
        """Each adjustment triggers a filter().update() call, then one commit."""
        adj1 = ScoreAdjustment(
            mapping_id=1, canonical_name="Condition", source_slug="src-a",
            old_score=0.9, new_score=0.72, reason="dead",
        )
        adj2 = ScoreAdjustment(
            mapping_id=2, canonical_name="Treatment", source_slug="src-b",
            old_score=0.8, new_score=0.84, reason="healthy",
        )

        session = MagicMock()
        apply_adjustments(session, [adj1, adj2])

        # Two query().filter().update() chains.
        assert session.query.return_value.filter.return_value.update.call_count == 2
        update_calls = (
            session.query.return_value.filter.return_value.update.call_args_list
        )
        assert update_calls[0] == call({"authority_score": 0.72})
        assert update_calls[1] == call({"authority_score": 0.84})

        session.commit.assert_called_once()

    def test_apply_empty_adjustments(self):
        """Empty adjustment list still commits but triggers no updates."""
        session = MagicMock()
        apply_adjustments(session, [])

        session.query.return_value.filter.return_value.update.assert_not_called()
        session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Edge cases from review
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_evaluate_multiple_mappings_per_concept_source(self):
        """Multiple local_names for the same (concept, source) each get a finding."""
        rows = [
            _make_mapping(1, "Condition", "src-a", local_name="Hypertension", authority_score=0.9),
            _make_mapping(2, "Condition", "src-a", local_name="High Blood Pressure", authority_score=0.9),
        ]
        session = _mock_session_with_mappings(rows)
        quality = {
            "Condition||src-a": _make_quality_entry(
                "Condition", "src-a", total_hits=5, precision=0.8,
            ),
        }
        findings = evaluate_mapping_quality(session, quality)
        assert len(findings) == 2
        local_names = {f.local_name for f in findings}
        assert local_names == {"Hypertension", "High Blood Pressure"}
        assert all(f.category == "healthy" for f in findings)

    @patch("retrieval_hub.ontology.self_improve.compute_authority_scores")
    def test_adjust_skips_missing_base_score(self, mock_compute):
        """Finding with no matching base score is skipped."""
        mock_compute.return_value = [(99, 0.9)]  # mapping_id=99, not matching id=1
        finding = MappingFinding(
            mapping_id=1, canonical_name="X", source_slug="s",
            local_name="L", category="dead", authority_score=0.8,
            metrics={"precision": 0, "is_dead": True},
        )
        adjustments = adjust_authority_scores(MagicMock(), [finding])
        assert len(adjustments) == 0
