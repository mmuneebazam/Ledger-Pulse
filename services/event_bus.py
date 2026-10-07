import json
import logging

from odoo import fields

from .auth import iso

_logger = logging.getLogger(__name__)


def channels_for(company_id, team_id=None):
    chans = ['ledger_pulse_c%d' % company_id]
    if team_id:
        chans.append('ledger_pulse_c%d_t%d' % (company_id, team_id))
    return chans


def lead_payload(lead):
    return {
        'id': lead.id,
        'name': lead.name,
        'score': lead.pulse_score,
        'sla_state': lead.sla_state,
        'sla_deadline': iso(lead.sla_deadline),
        'team_id': lead.team_id.id or False,
        'team_name': lead.team_id.name or '',
        'channel': lead.source_channel,
        'expected_revenue': lead.expected_revenue,
    }


def emit(env, event_type, record=None, payload=None):
    """Write the event to the pulse.event queue FIRST, then dispatch on the bus."""
    company = env.company
    team = env['crm.team']
    if record:
        if 'company_id' in record._fields and record.company_id:
            company = record.company_id
        if 'team_id' in record._fields:
            team = record.team_id
    ev = env['pulse.event'].sudo().create({
        'event_type': event_type,
        'res_model': record._name if record else False,
        'res_id': record.id if record else 0,
        'payload': json.dumps(payload or {}, default=str),
        'company_id': company.id,
        'team_id': team.id or False,
    })
    dispatch(ev)
    return ev


def dispatch(ev):
    message = {
        'event': ev.event_type,
        'event_id': ev.id,
        'res_model': ev.res_model,
        'res_id': ev.res_id,
        'company_id': ev.company_id.id,
        'team_id': ev.team_id.id or False,
        'payload': json.loads(ev.payload or '{}'),
    }
    try:
        bus = ev.env['bus.bus'].sudo()
        for channel in channels_for(ev.company_id.id, ev.team_id.id):
            bus._sendone(channel, 'ledger_pulse', message)
        ev.write({'state': 'dispatched', 'dispatched_at': fields.Datetime.now(), 'error': False})
    except Exception as exc:
        _logger.exception("LedgerPulse: dispatch failed for event %s", ev.id)
        ev.write({'state': 'failed', 'retry_count': ev.retry_count + 1, 'error': str(exc)[:500]})