import json
import logging

from odoo import fields, models

from . import event_bus

_logger = logging.getLogger(__name__)
MIN_SCORE, MAX_SCORE = 0, 100


def _value(lead, fname):
    val = lead[fname]
    if isinstance(val, models.BaseModel):
        return val.display_name if val else False
    return val


def _matches(actual, op, expected):
    if op == 'set':
        return bool(actual)
    if op == 'not_set':
        return not actual
    if op in ('contains', 'not_contains'):
        hit = (expected or '').lower() in str(actual or '').lower()
        return hit if op == 'contains' else not hit
    try:
        a, e = float(actual or 0), float(expected)
    except (TypeError, ValueError):
        a, e = str(actual or ''), str(expected or '')
    return {
        'eq': a == e, 'neq': a != e,
        'gt': a > e, 'gte': a >= e, 'lt': a < e, 'lte': a <= e,
    }.get(op, False)


def rules_for(env, company_id):
    return env['crm.lead.score.rule'].sudo().search([
        ('active', '=', True),
        '|', ('company_id', '=', False), ('company_id', '=', company_id),
    ])


def watched_fields(env):
    return set(env['crm.lead.score.rule'].sudo().search(
        [('active', '=', True)]).mapped('field_name'))


def compute(lead, rules):
    total, lines = 0, []
    for rule in rules:
        if _matches(_value(lead, rule.field_name), rule.operator, rule.value):
            total += rule.points
            lines.append('%+d  %s (%s %s %s)' % (
                rule.points, rule.name, rule.field_name, rule.operator, rule.value or ''))
    score = max(MIN_SCORE, min(MAX_SCORE, total))
    if score != total:
        lines.append('Capped to %d (raw %d)' % (score, total))
    return score, '\n'.join(lines) or 'No rules matched.'


def score_lead(lead, emit=True):
    company_id = lead.company_id.id or lead.env.company.id
    score, why = compute(lead, rules_for(lead.env, company_id))
    changed = lead.pulse_score != score
    if changed or lead.pulse_score_explanation != why:
        lead.with_context(pulse_skip=True).write({
            'pulse_score': score, 'pulse_score_explanation': why})
        if emit and changed:
            event_bus.emit(lead.env, 'lead.scored', lead, event_bus.lead_payload(lead))
    return score


def bulk_rescore(env, domain=None, batch=500):
    """Rescore many leads in batches with a commit per batch, tracked by pulse.job."""
    env = env(context=dict(env.context, pulse_skip=True, tracking_disable=True))
    Lead = env['crm.lead']
    ids = Lead.search(domain or [('active', '=', True)]).ids
    job = env['pulse.job'].sudo().create({
        'name': 'bulk_rescore', 'args': json.dumps({'leads': len(ids), 'batch': batch})})
    job.start()
    env.cr.commit()

    rule_cache, changed = {}, 0
    try:
        for i in range(0, len(ids), batch):
            for lead in Lead.browse(ids[i:i + batch]):
                cid = lead.company_id.id or env.company.id
                if cid not in rule_cache:
                    rule_cache[cid] = rules_for(env, cid)
                score, why = compute(lead, rule_cache[cid])
                if lead.pulse_score != score or lead.pulse_score_explanation != why:
                    lead.write({'pulse_score': score, 'pulse_score_explanation': why})
                    changed += 1
            env.cr.commit()
            env.invalidate_all()
        job.finish(json.dumps({'scored': len(ids), 'changed': changed}))
    except Exception as exc:
        env.cr.rollback()
        job.fail(str(exc)[:500])
        _logger.exception("bulk_rescore failed")
    env.cr.commit()
    return len(ids), changed