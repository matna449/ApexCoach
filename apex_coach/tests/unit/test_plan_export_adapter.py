from apex_coach.adapters.plan_export_adapter import MockPlanExportAdapter

SESSION = {"day": "Monday", "session_type": "Strength", "structure": {"type": "single_block", "duration_min": 45.0}}


def test_mock_push_session_creates_when_no_existing_id():
    adapter = MockPlanExportAdapter()
    assert adapter.push_session("2026-08-03", SESSION, None) == "mock-event-2026-08-03"


def test_mock_push_session_echoes_existing_id_on_update():
    adapter = MockPlanExportAdapter()
    assert adapter.push_session("2026-08-03", SESSION, "existing-id") == "existing-id"
