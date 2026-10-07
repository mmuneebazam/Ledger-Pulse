import base64
import hashlib
import json
import re
from datetime import datetime, timezone

import psycopg2

from odoo import fields, http

from ..services.auth import ApiError, api_call, iso

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
IDEM_RE = re.compile(r'^[A-Za-z0-9_.:\-]{1,200}$')
CHANNELS = ['website', 'api', 'partner', 'email', 'phone', 'other']

LEAD_FIELDS = {
    'name', 'contact_name', 'email_from', 'phone', 'partner_name',
    'company_name',  # deprecated alias of partner_name
    'expected_revenue', 'description', 'source_channel',
}
LIST_PARAMS = {'limit', 'cursor', 'created_from', 'created_to',
               'team_id', 'min_score', 'max_score'}


# ------------------------------------------------------------ serializers
def lead_to_dict(lead):
    return {
        'id': lead.id,
        'name': lead.name,
        'contact_name': lead.contact_name or None,
        'partner_name': lead.partner_name or None,
        'email_from': lead.email_from or None,
        'phone': lead.phone or None,
        'expected_revenue': lead.expected_revenue,
        'source_channel': lead.source_channel,
        'pulse_score': lead.pulse_score,
        'sla_state': lead.sla_state,
        'sla_deadline': iso(lead.sla_deadline),
        'team': {'id': lead.team_id.id, 'name': lead.team_id.name} if lead.team_id else None,
        'stage': lead.stage_id.name or None,
        'created_at': iso(lead.create_date),
    }


# ------------------------------------------------------------ validation
def _clean_str(body, field, max_len, required=False):
    val = body.get(field)
    if val is None:
        if required:
            raise ApiError(422, 'missing_field', "'%s' is required." % field, field=field)
        return None
    if not isinstance(val, str):
        raise ApiError(422, 'invalid_type', "'%s' must be a string." % field, field=field)
    val = val.strip()
    if required and not val:
        raise ApiError(422, 'missing_field', "'%s' is required." % field, field=field)
    if len(val) > max_len:
        raise ApiError(422, 'too_long',
                       "'%s' must be at most %d characters." % (field, max_len), field=field)
    return val or None


def _validate_lead(body):
    unknown = sorted(set(body) - LEAD_FIELDS)
    if unknown:
        raise ApiError(422, 'unknown_field', "Unknown field: '%s'." % unknown[0], field=unknown[0])

    warnings = []
    vals = {'name': _clean_str(body, 'name', 255, required=True)}

    for field in ('contact_name', 'phone'):
        v = _clean_str(body, field, 255)
        if v:
            vals[field] = v

    partner_name = _clean_str(body, 'partner_name', 255)
    legacy = _clean_str(body, 'company_name', 255)
    if legacy:
        warnings.append({
            'field': 'company_name',
            'message': "Deprecated, use 'partner_name'. It will be removed in a future API version.",
        })
        partner_name = partner_name or legacy
    if partner_name:
        vals['partner_name'] = partner_name

    email = _clean_str(body, 'email_from', 254)
    if email:
        if not EMAIL_RE.match(email):
            raise ApiError(422, 'invalid_email', "'email_from' is not a valid email.", field='email_from')
        vals['email_from'] = email

    if body.get('expected_revenue') is not None:
        rev = body['expected_revenue']
        if isinstance(rev, bool) or not isinstance(rev, (int, float)) or rev < 0:
            raise ApiError(422, 'invalid_value',
                           "'expected_revenue' must be a number >= 0.", field='expected_revenue')
        vals['expected_revenue'] = rev

    desc = _clean_str(body, 'description', 10000)
    if desc:
        vals['description'] = desc

    channel = body.get('source_channel', 'api')
    if channel not in CHANNELS:
        raise ApiError(422, 'invalid_value',
                       "'source_channel' must be one of: %s." % ', '.join(CHANNELS),
                       field='source_channel')
    vals['source_channel'] = channel
    return vals, warnings


def _reject_unknown_params(params):
    for p in params:
        if p not in LIST_PARAMS:
            raise ApiError(422, 'unknown_parameter', "Unknown query parameter: '%s'." % p, field=p)


def _int_param(params, name, default=None, min_=None, max_=None):
    raw = params.get(name)
    if raw in (None, ''):
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ApiError(422, 'invalid_parameter', "'%s' must be an integer." % name, field=name)
    if min_ is not None and val < min_:
        raise ApiError(422, 'invalid_parameter', "'%s' must be >= %d." % (name, min_), field=name)
    if max_ is not None and val > max_:
        raise ApiError(422, 'invalid_parameter', "'%s' must be <= %d." % (name, max_), field=name)
    return val


def _dt_param(params, name):
    raw = params.get(name)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
    except ValueError:
        raise ApiError(422, 'invalid_parameter',
                       "'%s' must be an ISO-8601 date or datetime." % name, field=name)
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _encode_cursor(last_id):
    raw = json.dumps({'id': last_id}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _decode_cursor(cursor):
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        last_id = data['id']
        if not isinstance(last_id, int) or isinstance(last_id, bool):
            raise ValueError
        return last_id
    except Exception:
        raise ApiError(422, 'invalid_cursor', 'The cursor is invalid.', field='cursor')


# ------------------------------------------------------------ handlers
def _health(ctx):
    try:
        ctx.env.cr.execute('SELECT 1')
    except Exception:
        raise ApiError(503, 'not_ready', 'Database is not reachable.')
    return {
        'status': 'ok',
        'api_version': 'v1',
        'time': iso(fields.Datetime.now()),
    }, 200


def _me(ctx):
    key, rate = ctx.key, ctx.rate
    return {
        'name': key.name,
        'key_prefix': key.key_prefix,
        'scopes': key._scope_list(),
        'company': {'id': ctx.company.id, 'name': ctx.company.name},
        'expires_at': iso(key.expires_at),
        'deprecated_until': iso(key.deprecated_until),
        'rate_limit': {
            'limit_per_min': rate['limit'],
            'used_this_minute': rate['used'],
            'remaining': rate['remaining'],
            'resets_in_seconds': rate['reset'],
        },
    }, 200


def _create_lead(ctx):
    body = ctx.json_body()

    idem_key = request_header('Idempotency-Key')
    if idem_key is not None and not IDEM_RE.match(idem_key):
        raise ApiError(422, 'invalid_idempotency_key',
                       'Idempotency-Key must be 1-200 chars: letters, digits, _ . : -',
                       field='Idempotency-Key')

    req_hash = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    Idem = ctx.env['pulse.idempotency']
    if idem_key:
        prev = Idem.search([('api_key_id', '=', ctx.key.id), ('key', '=', idem_key)], limit=1)
        if prev:
            if prev.request_hash != req_hash:
                raise ApiError(409, 'idempotency_conflict',
                               'This Idempotency-Key was already used with a different request body.',
                               field='Idempotency-Key')
            return json.loads(prev.response_body), prev.status_code, {'Idempotent-Replayed': 'true'}

    vals, warnings = _validate_lead(body)
    vals.update({
        'type': 'opportunity',
        'user_id': False,
        'company_id': ctx.company.id,
    })
    lead = ctx.env['crm.lead'].create(vals)

    data = {'data': lead_to_dict(lead), 'warnings': warnings}
    headers = {'Location': '/api/v1/leads/%d' % lead.id}
    if warnings:
        headers['Deprecation'] = 'true'

    if idem_key:
        try:
            with ctx.env.cr.savepoint():
                Idem.create({
                    'api_key_id': ctx.key.id,
                    'key': idem_key,
                    'endpoint': '/api/v1/leads',
                    'request_hash': req_hash,
                    'status_code': 201,
                    'response_body': json.dumps(data),
                })
        except psycopg2.IntegrityError:
            # a concurrent request with the same key won the race
            raise ApiError(409, 'idempotency_in_progress',
                           'A request with this Idempotency-Key is already being processed.',
                           field='Idempotency-Key')
    return data, 201, headers


def request_header(name):
    from odoo.http import request
    val = request.httprequest.headers.get(name)
    return val.strip() if val else None


def _get_lead(ctx, lead_id):
    lead = ctx.env['crm.lead'].search([
        ('id', '=', lead_id),
        ('company_id', 'in', [False, ctx.company.id]),
    ], limit=1)
    if not lead:
        raise ApiError(404, 'not_found', 'Lead not found.')
    return {'data': lead_to_dict(lead)}, 200


def _list_leads(ctx):
    params = ctx.params
    _reject_unknown_params(params)

    limit = _int_param(params, 'limit', default=20, min_=1, max_=100)
    domain = [('company_id', 'in', [False, ctx.company.id])]

    if params.get('cursor'):
        domain.append(('id', '<', _decode_cursor(params['cursor'])))

    created_from = _dt_param(params, 'created_from')
    created_to = _dt_param(params, 'created_to')
    if created_from:
        domain.append(('create_date', '>=', created_from))
    if created_to:
        domain.append(('create_date', '<=', created_to))

    team_id = _int_param(params, 'team_id')
    if team_id is not None:
        domain.append(('team_id', '=', team_id))
    min_score = _int_param(params, 'min_score')
    if min_score is not None:
        domain.append(('pulse_score', '>=', min_score))
    max_score = _int_param(params, 'max_score')
    if max_score is not None:
        domain.append(('pulse_score', '<=', max_score))

    leads = ctx.env['crm.lead'].search(domain, order='id desc', limit=limit + 1)
    has_more = len(leads) > limit
    page = leads[:limit]
    return {
        'data': [lead_to_dict(l) for l in page],
        'page': {
            'limit': limit,
            'has_more': has_more,
            'next_cursor': _encode_cursor(page[-1].id) if has_more and page else None,
        },
    }, 200


# ------------------------------------------------------------ routes
class LedgerPulseApiV1(http.Controller):

    @http.route('/api/v1/health', type='http', auth='public', methods=['GET'], csrf=False)
    def health(self, **kw):
        return api_call(_health, public=True)

    @http.route('/api/v1/me', type='http', auth='public', methods=['GET'], csrf=False)
    def me(self, **kw):
        return api_call(_me)

    @http.route('/api/v1/leads', type='http', auth='public', methods=['POST'], csrf=False)
    def create_lead(self, **kw):
        return api_call(_create_lead, scope='leads.write')

    @http.route('/api/v1/leads', type='http', auth='public', methods=['GET'], csrf=False)
    def list_leads(self, **kw):
        return api_call(_list_leads, scope='leads.read')

    @http.route('/api/v1/leads/<int:lead_id>', type='http', auth='public',
                methods=['GET'], csrf=False)
    def get_lead(self, lead_id, **kw):
        return api_call(lambda ctx: _get_lead(ctx, lead_id), scope='leads.read')