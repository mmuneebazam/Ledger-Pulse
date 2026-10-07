import hashlib
import hmac
import json

import psycopg2

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..services import cash_bridge_engine
from ..services.auth import ApiError, api_call, iso

WEBHOOK_FIELDS = {'event', 'event_id', 'invoice_id', 'amount', 'currency', 'reference'}


def _invoice_status(ctx, invoice_id):
    # Only invoices that belong to a CRM-to-cash bridge of the key's own company.
    bridge = ctx.env['pulse.cash.bridge'].search([
        ('move_id', '=', invoice_id), ('company_id', '=', ctx.company.id)], limit=1)
    if not bridge:
        raise ApiError(404, 'not_found', 'Invoice not found.')
    m = bridge.move_id
    return {'data': {
        'invoice_id': m.id,
        'number': m.name if m.state == 'posted' else None,
        'state': m.state,
        'payment_state': m.payment_state,
        'bridge_state': bridge.state,
        'amount_total': m.amount_total,
        'amount_residual': m.amount_residual,
        'currency': m.currency_id.name,
        'due_date': str(m.invoice_date_due) if m.invoice_date_due else None,
        'lead_id': bridge.lead_id.id,
    }}, 200


def _webhook(ctx):
    raw = request.httprequest.get_data()
    secret = ctx.env['ir.config_parameter'].sudo().get_param('ledger_pulse.webhook_secret')
    if not secret:
        raise ApiError(503, 'webhook_not_configured', 'Webhook secret is not configured.')
    expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    given = request.httprequest.headers.get('X-Pulse-Signature', '')
    if not hmac.compare_digest(expected, given):
        raise ApiError(401, 'invalid_signature', 'Webhook signature verification failed.')

    body = ctx.json_body()
    unknown = sorted(set(body) - WEBHOOK_FIELDS)
    if unknown:
        raise ApiError(422, 'unknown_field', "Unknown field: '%s'." % unknown[0], field=unknown[0])
    if body.get('event') != 'payment.succeeded':
        raise ApiError(422, 'unsupported_event', "Only 'payment.succeeded' is supported.", field='event')
    event_id = body.get('event_id')
    if not isinstance(event_id, str) or not (1 <= len(event_id) <= 100):
        raise ApiError(422, 'invalid_value', "'event_id' must be a string (1-100 chars).", field='event_id')
    invoice_id = body.get('invoice_id')
    if isinstance(invoice_id, bool) or not isinstance(invoice_id, int):
        raise ApiError(422, 'invalid_value', "'invoice_id' must be an integer.", field='invoice_id')
    amount = body.get('amount')
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise ApiError(422, 'invalid_value', "'amount' must be a number > 0.", field='amount')

    Receipt = ctx.env['pulse.webhook.receipt']
    if Receipt.search_count([('event_id', '=', event_id)]):
        return {'status': 'duplicate', 'event_id': event_id}, 200

    bridge = ctx.env['pulse.cash.bridge'].search([('move_id', '=', invoice_id)], limit=1)
    if not bridge:
        raise ApiError(404, 'not_found', 'Invoice not found.')
    move = bridge.move_id
    if move.state != 'posted' or move.payment_state in ('paid', 'in_payment', 'reversed'):
        raise ApiError(409, 'invoice_not_payable', 'Invoice is not open for payment.')
    currency = body.get('currency')
    if currency and currency != move.currency_id.name:
        raise ApiError(422, 'currency_mismatch', 'Currency does not match the invoice.', field='currency')
    if amount > move.amount_residual + move.currency_id.rounding:
        raise ApiError(422, 'overpayment', 'Amount exceeds the open balance.', field='amount')

    try:
        with ctx.env.cr.savepoint():
            receipt = Receipt.create({
                'event_id': event_id, 'event_type': body['event'], 'move_id': move.id,
                'amount': amount, 'company_id': move.company_id.id})
    except psycopg2.IntegrityError:
        return {'status': 'duplicate', 'event_id': event_id}, 200

    try:
        payments = cash_bridge_engine.register_payment(
            move.with_company(move.company_id), amount=amount,
            reference=body.get('reference') or event_id)
    except UserError as exc:
        raise ApiError(409, 'payment_rejected', str(exc))
    receipt.write({'payment_id': payments[:1].id, 'status': 'registered'})
    # NOTE: payment_state stays 'in_payment' until the bank statement line is matched.
    return {'status': 'registered', 'event_id': event_id, 'invoice': {
        'invoice_id': move.id, 'payment_state': move.payment_state,
        'amount_residual': move.amount_residual}}, 200


class LedgerPulseApiV1Finance(http.Controller):

    @http.route('/api/v1/invoices/<int:invoice_id>/status', type='http', auth='public',
                methods=['GET'], csrf=False)
    def invoice_status(self, invoice_id, **kw):
        return api_call(lambda ctx: _invoice_status(ctx, invoice_id), scope='invoices.read')

    @http.route('/api/v1/webhooks/inbound', type='http', auth='public',
                methods=['POST'], csrf=False)
    def webhook_inbound(self, **kw):
        # No API key here: the HMAC signature is the authentication.
        return api_call(_webhook, public=True)