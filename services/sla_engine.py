import logging
from datetime import timedelta

from odoo import fields

from . import event_bus

_logger = logging.getLogger(__name__)


def resolve_policy(env, team, channel, company):
    """Most specific policy wins: team+channel > team > channel > default.
    Tie-breaker: lowest sequence (policies are ordered by sequence, id)."""
    policies = env['pulse.sla.policy'].sudo().search([
        ('active', '=', True),
        '|', ('company_id', '=', False), ('company_id', '=', company.id)])
    best, best_rank = None, -1
    for pol in policies:
        if pol.team_id and pol.team_id != team:
            continue
        if pol.source_channel and pol.source_channel != channel:
            continue
        rank = (2 if pol.team_id else 0) + (1 if pol.source_channel else 0)
        if rank > best_rank:
            best, best_rank = pol, rank
    return best


def apply_sla(lead):
    """Resolve the policy at creation and freeze the deadline."""
    if lead.sla_deadline:
        return
    company = lead.company_id or lead.env.company
    pol = resolve_policy(lead.env, lead.team_id, lead.source_channel, company)
    if not pol:
        return
    base = lead.create_date or fields.Datetime.now()
    lead.with_context(pulse_skip=True).write({
        'sla_deadline': base + timedelta(hours=pol.hours),
        'sla_state': 'ok',
    })


def sweep_breached(env, batch=500, max_loops=200):
    """Idempotent: only leads still in state 'ok' are touched, in batches."""
    env = env(context=dict(env.context, pulse_skip=True, tracking_disable=True))
    Lead = env['crm.lead']
    total = 0
    for _ in range(max_loops):
        leads = Lead.search([
            ('sla_state', '=', 'ok'), ('sla_deadline', '<', fields.Datetime.now()),
            ('active', '=', True), ('probability', '<', 100)], limit=batch)
        if not leads:
            break
        leads.write({'sla_state': 'breached'})
        for lead in leads:
            event_bus.emit(env, 'sla.breached', lead, event_bus.lead_payload(lead))
        total += len(leads)
        env.cr.commit()
        env.invalidate_all()
    if total:
        _logger.info("LedgerPulse: %d SLA breaches swept", total)
    return total