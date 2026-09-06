"""WEB-0 correlation and secret-safe event contracts, without runtime wiring."""

import json
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from netbox_sync.application.contracts import RunContext
from netbox_sync.application.observability import (
    Component, ErrorCode, RunEvent, run_event_record,
)


def test_run_context_roundtrip_and_immutability():
    first = RunContext('esxi-infra-test')
    worker = RunContext(first.source_instance, UUID(str(first.run_id)))
    assert worker == first
    assert RunContext(first.source_instance).run_id != first.run_id
    with pytest.raises(FrozenInstanceError):
        first.source_instance = 'pve-infra-test'


@pytest.mark.parametrize('source', ['', 'INVALID SOURCE', None])
def test_context_rejects_invalid_source(source):
    with pytest.raises(ValueError):
        RunContext(source)


@pytest.mark.parametrize('run_id', [UUID(int=0), 'not-a-uuid'])
def test_context_rejects_invalid_run_id(run_id):
    with pytest.raises(ValueError):
        RunContext('esxi-infra-test', run_id)


def test_event_is_json_ready_and_keeps_correlation(capsys):
    context = RunContext('esxi-infra-test')
    event = run_event_record(
        context, Component.WORKER, RunEvent.FAILED,
        error_code=ErrorCode.SOURCE_AUTH_FAILED,
    )
    assert json.loads(json.dumps(event)) == event
    assert event['run_id'] == str(context.run_id)
    assert event['message'] == 'Run failed'
    assert event['error_code'] == 'SOURCE_AUTH_FAILED'
    assert event['level'] == 'ERROR'
    assert event['timestamp'].endswith('+00:00')
    assert capsys.readouterr().out == ''


def test_event_refuses_arbitrary_exception_and_message():
    context = RunContext('esxi-infra-test')
    with pytest.raises(TypeError):
        run_event_record(context, Component.WORKER, 'password=FAKE_SECRET')
    with pytest.raises(TypeError):
        run_event_record(context, Component.WORKER, RunEvent.FAILED,
                         error_code=RuntimeError('password=FAKE_SECRET'))
    with pytest.raises(ValueError):
        run_event_record(context, Component.WORKER, RunEvent.FAILED)
    with pytest.raises(ValueError):
        run_event_record(context, Component.WORKER, RunEvent.STARTED,
                         error_code=ErrorCode.RUN_INTERNAL_FAILED)
