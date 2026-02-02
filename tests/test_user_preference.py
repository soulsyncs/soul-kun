"""
lib/memory/user_preference.py のテスト

対象:
- save/retrieve/get_preference/delete_preference
- learn_from_interaction
- update_from_emotion_detection
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from lib.memory.user_preference import UserPreference
from lib.memory.constants import PreferenceType, LearnedFrom
from lib.memory.exceptions import ValidationError


@pytest.mark.asyncio
async def test_save_validates_preference_type_and_confidence():
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = ("id-1", 0.7, 2)
    mock_conn.execute.return_value = mock_result

    pref = UserPreference(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
    result = await pref.save(
        user_id="22222222-2222-2222-2222-222222222222",
        preference_type=PreferenceType.RESPONSE_STYLE.value,
        preference_key="tone",
        preference_value={"style": "detailed"},
        confidence=1.5,
    )

    assert result.success is True
    assert result.data["confidence"] <= 1.0
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_save_invalid_preference_type_raises():
    pref = UserPreference(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
    with pytest.raises(ValidationError):
        await pref.save(
            user_id="22222222-2222-2222-2222-222222222222",
            preference_type="invalid",
            preference_key="tone",
            preference_value="x",
        )


@pytest.mark.asyncio
async def test_retrieve_parses_json_value():
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        (
            "id-1",
            "org-1",
            "user-1",
            PreferenceType.RESPONSE_STYLE.value,
            "tone",
            '{"style": "detailed"}',
            LearnedFrom.AUTO.value,
            0.6,
            3,
            "internal",
            None,
            None,
        )
    ]
    mock_conn.execute.return_value = mock_result

    pref = UserPreference(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
    results = await pref.retrieve(user_id="22222222-2222-2222-2222-222222222222")

    assert results[0].preference_value["style"] == "detailed"


@pytest.mark.asyncio
async def test_get_preference_returns_none_when_missing():
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_conn.execute.return_value = mock_result

    pref = UserPreference(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
    result = await pref.get_preference(
        user_id="22222222-2222-2222-2222-222222222222",
        preference_type=PreferenceType.RESPONSE_STYLE.value,
        preference_key="tone",
    )

    assert result is None


@pytest.mark.asyncio
async def test_learn_from_interaction_generates_results():
    pref = UserPreference(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)

    async def fake_save(*args, **kwargs):
        class R:
            success = True
        return R()

    pref.save = fake_save  # monkeypatch without fixture

    results = await pref.learn_from_interaction(
        user_id="22222222-2222-2222-2222-222222222222",
        interaction_type="message",
        interaction_data={"content": "😊 ありがとう", "timestamp": datetime.utcnow()},
    )

    assert len(results) >= 2


@pytest.mark.asyncio
async def test_update_from_emotion_detection_sets_trend():
    pref = UserPreference(conn=MagicMock(), org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)

    async def fake_save(*args, **kwargs):
        class R:
            success = True
            data = {}
        return R()

    pref.save = fake_save
    result = await pref.update_from_emotion_detection(
        user_id="22222222-2222-2222-2222-222222222222",
        baseline_score=0.5,
        current_score=0.3,
        volatility=0.2,
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_delete_preference_returns_count():
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.rowcount = 4
    mock_conn.execute.return_value = mock_result

    pref = UserPreference(conn=mock_conn, org_id="11111111-1111-1111-1111-111111111111", openrouter_api_key=None)
    deleted = await pref.delete_preference(user_id="22222222-2222-2222-2222-222222222222")

    assert deleted == 4
    mock_conn.commit.assert_called_once()
