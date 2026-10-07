import json
import logging
import time

from odoo import SUPERUSER_ID, fields
from odoo.http import Response, request

_logger = logging.getLogger(__name__)

ISO_FMT = '%Y-%m-%dT%H:%M:%SZ'


def iso(dt):
    return dt.strftime(ISO_FMT) if dt else None


class ApiError(Exception):
    def __init__(self, status, code, message, field=None, headers=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.headers = headers or {}


def json_response(data, status=200, headers=None):
    hdrs = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
    for k, v in (headers or {}).items():
        hdrs.append((k, str(v)))
    return Response(json.dumps(data, default=str), status=status, headers=hdrs)


def error_response(err):
    body = {'error': {'code': err.code, 'message': err.message, 'field': err.field}}
    return json_response(body, err.status, err.headers)


class ApiContext:
    """Everything a handler needs: a superuser env scoped to the key's company."""

    def __init__(self, env, key, config, rate=None):
        self.env = env
        self.key = key
        self.config = config
        self.rate = rate
        self.company = key.company_id if key else None

    @property
    def params(self):
        return request.httprequest.args

    def json_body(self):
        raw = request.httprequest.get_data(as_text=True)
        if not raw.strip():
            raise ApiError(400, 'empty_body', 'Request body is required.')
        try:
            data = json.loads(raw)
        except ValueError:
            raise ApiError(400, 'invalid_json', 'Request body is not valid JSON.')
        if not isinstance(data, dict):
            raise ApiError(400, 'invalid_body', 'JSON body must be an object.')
        return data


# ---------------------------------------------------------------- helpers
def _extract_token():
    headers = request.httprequest.headers
    auth = headers.get('Authorization', '')
    if auth.lower().startswith('bearer '):
        return auth[7:].strip()
    return (headers.get('X-API-Key') or '').strip()


def _authenticate(env):
    token = _extract_token()
    www = {'WWW-Authenticate': 'Bearer'}
    if not token:
        raise ApiError(
            401, 'missing_credentials',
            'Provide an API key via "Authorization: Bearer <key>" or "X-API-Key".',
            headers=www)
    key = env['pulse.api.key'].authenticate(token)
    if not key:
        raise ApiError(
            401, 'invalid_api_key',
            'The API key is invalid, expired or revoked.', headers=www)
    return key


def _rate_headers(rate):
    return {
        'X-RateLimit-Limit': rate['limit'],
        'X-RateLimit-Remaining': rate['remaining'],
        'X-RateLimit-Reset': rate['reset'],
    }


def _check_rate_limit(env, key, config):
    limit = config.rate_limit_per_min
    hits, _bucket = env['pulse.rate.limit'].register_hit(key.id)
    reset = 60 - int(time.time()) % 60
    rate = {
        'limit': limit,
        'used': hits,
        'remaining': max(limit - hits, 0),
        'reset': reset,
    }
    if hits > limit:
        headers = _rate_headers(rate)
        headers['Retry-After'] = reset
        raise ApiError(
            429, 'rate_limited',
            'Rate limit exceeded. Retry after %d seconds.' % reset,
            headers=headers)
    return rate


def _check_scope(key, scope):
    if scope and scope not in key._scope_list():
        raise ApiError(
            403, 'insufficient_scope',
            'This API key lacks the required scope: %s' % scope)


def _touch_key(key):
    now = fields.Datetime.now()
    if not key.last_used_at or (now - key.last_used_at).total_seconds() > 60:
        key.last_used_at = now


# ---------------------------------------------------------------- main entry
def api_call(handler, scope=None, public=False):
    """Run `handler(ctx)` with auth, rate limit, scope check, error envelope
    and request logging. The handler returns (data, status[, extra_headers])."""
    started = time.time()
    req = request.httprequest
    env = request.env(user=SUPERUSER_ID)
    key = None
    rate_headers = {}
    status = 500

    try:
        if public:
            ctx = ApiContext(env, None, None)
        else:
            key = _authenticate(env)
            env = env(context=dict(env.context, allowed_company_ids=[key.company_id.id]))
            config = env['pulse.config'].get_config(key.company_id)
            rate = _check_rate_limit(env, key, config)
            rate_headers = _rate_headers(rate)
            _check_scope(key, scope)
            _touch_key(key)
            ctx = ApiContext(env, key, config, rate)

        # savepoint: a failing handler rolls back only its own work, so the
        # rate-limit hit and the request log are still kept.
        with env.cr.savepoint():
            result = handler(ctx)
        data, status = result[0], result[1]
        headers = dict(rate_headers)
        if len(result) > 2:
            headers.update(result[2])
        response = json_response(data, status, headers)

    except ApiError as err:
        status = err.status
        merged = dict(rate_headers)
        merged.update(err.headers)
        err.headers = merged
        response = error_response(err)

    except Exception:
        _logger.exception("LedgerPulse API unexpected error on %s %s", req.method, req.path)
        env.cr.rollback()
        status = 500
        response = error_response(ApiError(
            500, 'internal_error', 'Unexpected server error.', headers=rate_headers))

    if not public:
        try:
            with env.cr.savepoint():
                env['pulse.request.log'].create({
                    'api_key_id': key.id if key else False,
                    'company_id': key.company_id.id if key else False,
                    'endpoint': req.path[:255],
                    'method': req.method,
                    'status_code': status,
                    'latency_ms': int((time.time() - started) * 1000),
                })
        except Exception:
            _logger.exception("LedgerPulse: could not write request log")

    return response