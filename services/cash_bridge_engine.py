import logging

from odoo import fields
from odoo.exceptions import UserError

from . import accounting_setup

_logger = logging.getLogger(__name__)


def ensure_partner(lead):
    if lead.partner_id:
        return lead.partner_id
    name = lead.partner_name or lead.contact_name or lead.name
    partner = lead.env['res.partner'].create({
        'name': name, 'email': lead.email_from, 'phone': lead.phone,
        'company_type': 'company' if lead.partner_name else 'person',
    })
    lead.with_context(pulse_skip=True, pulse_no_invoice=True).write({'partner_id': partner.id})
    return partner


def create_invoice_for_lead(lead):
    """Won lead -> DRAFT customer invoice, linked through pulse.cash.bridge.
    Payment terms come from Odoo's engine, taxes from product + fiscal position."""
    env = lead.env
    Bridge = env['pulse.cash.bridge']
    live = lead.pulse_bridge_ids.filtered(lambda b: b.state != 'cancel')
    if live:
        return live[0]
    amount = lead.expected_revenue or 0.0
    if amount <= 0:
        return Bridge

    company = lead.company_id or env.company
    cfg = env['pulse.config'].get_config(company)
    if not cfg.invoice_product_id:
        accounting_setup.ensure_demo_setup(env, company)
        cfg = env['pulse.config'].get_config(company)
    product = cfg.invoice_product_id
    term = cfg.invoice_payment_term_id

    partner = ensure_partner(lead)
    analytic = accounting_setup.get_team_analytic_account(env, lead.team_id, company)
    move = env['account.move'].with_company(company).create({
        'move_type': 'out_invoice',
        'partner_id': partner.id,
        'invoice_date': fields.Date.context_today(lead),
        'invoice_origin': lead.name,
        'invoice_user_id': lead.user_id.id or False,
        'invoice_payment_term_id': term.id if term else False,
        'company_id': company.id,
        'invoice_line_ids': [(0, 0, {
            'product_id': product.id,
            'name': lead.name,
            'quantity': 1.0,
            'price_unit': amount,
            'analytic_distribution': {str(analytic.id): 100.0},
        })],
    })
    bridge = Bridge.sudo().create({'lead_id': lead.id, 'move_id': move.id})
    lead.sudo().message_post(body="Draft invoice created from won opportunity: %s" % move.display_name)
    return bridge


def register_payment(move, amount=None, date=None, reference=None):
    """Register a payment on a posted invoice; Odoo reconciles it automatically."""
    env = move.env
    if move.state != 'posted':
        raise UserError("Only posted invoices can be paid.")
    if move.payment_state in ('paid', 'in_payment', 'reversed'):
        raise UserError("This invoice is already settled.")
    residual = move.amount_residual
    amount = residual if amount is None else amount
    if amount <= 0 or amount > residual + move.currency_id.rounding:
        raise UserError("Payment amount must be between 0 and the residual %.2f." % residual)
    wizard = env['account.payment.register'].with_context(
        active_model='account.move', active_ids=move.ids
    ).create({
        'amount': amount,
        'payment_date': date or fields.Date.context_today(move),
        'communication': reference or move.name,
    })
    payments = wizard._create_payments()
    bridge = env['pulse.cash.bridge'].sudo().search([('move_id', '=', move.id)], limit=1)
    if bridge and payments:
        bridge.payment_id = payments[:1]
    return payments


def issue_credit_note(move, amount=None, reason='Service downgrade'):
    """Credit note against a posted invoice, reconciled against it (not a loose negative)."""
    env = move.env
    if move.state != 'posted' or move.move_type != 'out_invoice':
        raise UserError("Credit notes can only be issued against posted customer invoices.")
    src = move.invoice_line_ids.filtered(lambda l: l.display_type == 'product')[:1]
    amount = amount or move.amount_untaxed
    credit = env['account.move'].with_company(move.company_id).create({
        'move_type': 'out_refund',
        'partner_id': move.partner_id.id,
        'invoice_date': fields.Date.context_today(move),
        'ref': reason,
        'reversed_entry_id': move.id,
        'invoice_origin': move.name,
        'currency_id': move.currency_id.id,
        'invoice_line_ids': [(0, 0, {
            'product_id': src.product_id.id,
            'name': reason,
            'quantity': 1.0,
            'price_unit': amount,
            'tax_ids': [(6, 0, src.tax_ids.ids)],
            'analytic_distribution': src.analytic_distribution,
        })],
    })
    credit.action_post()
    lines = (move.line_ids | credit.line_ids).filtered(
        lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
    lines.reconcile()
    return credit