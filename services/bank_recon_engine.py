import csv
import itertools
import logging

from odoo import fields
from odoo.exceptions import UserError

from . import event_bus

_logger = logging.getLogger(__name__)


def _ensure_reconcilable(accounts):
    for acc in accounts:
        if not acc.reconcile:
            acc.sudo().reconcile = True


def _general_journal(env, company):
    journal = env['account.journal'].search(
        [('type', '=', 'general'), ('company_id', '=', company.id)], limit=1)
    if not journal:
        raise UserError("No miscellaneous journal found.")
    return journal


def _account(env, company, code, name, account_type):
    Account = env['account.account']
    acc = Account.search([('company_id', '=', company.id), ('code', '=', code)], limit=1)
    return acc or Account.create({
        'code': code, 'name': name, 'account_type': account_type, 'company_id': company.id})


def bank_charges_account(env, company):
    return _account(env, company, 'PBNKCHG', 'Bank Charges (LedgerPulse)', 'expense')


def unexplained_account(env, company):
    # Money we cannot explain yet sits as a LIABILITY until someone identifies it.
    return _account(env, company, 'PUNEX01', 'Unexplained Bank Receipts', 'liability_current')


def import_statement_csv(env, journal, path):
    """CSV columns: date,payment_ref,partner,amount"""
    Line = env['account.bank.statement.line']
    created = Line
    with open(path, newline='', encoding='utf-8') as fh:
        for row in csv.DictReader(fh):
            partner = env['res.partner']
            if row.get('partner'):
                partner = partner.search([('name', '=', row['partner'])], limit=1)
            created |= Line.create({
                'journal_id': journal.id,
                'date': row['date'],
                'payment_ref': row['payment_ref'],
                'partner_id': partner.id or False,
                'amount': float(row['amount']),
            })
    return created


def _payments_to_emit(env, payments):
    bridges = env['pulse.cash.bridge'].sudo().search(
        [('move_id', 'in', payments.reconciled_invoice_ids.ids)])
    for b in bridges:
        event_bus.emit(env, 'payment.reconciled', b.lead_id, {
            'id': b.lead_id.id, 'name': b.move_id.name, 'invoice_id': b.move_id.id})


def match(stmt_line, payments, kind='clean', note=False):
    """Match one statement line to one or more posted payments.

    Statement:  Dr Bank / Cr Suspense
    Payment:    Dr Outstanding Receipts / Cr Receivable
    Clearing:   Dr Suspense / Cr Outstanding Receipts   <- created here
    Then both pairs of lines on Suspense and on Outstanding are reconciled."""
    env = stmt_line.env
    if stmt_line.pulse_matched:
        raise UserError("Statement line is already matched.")
    company = stmt_line.journal_id.company_id
    liquidity, suspense, other = stmt_line._seek_for_lines()
    if not suspense:
        raise UserError("Statement line has no suspense line (already reconciled inside Odoo).")

    pay_lines = env['account.move.line']
    for pay in payments:
        if pay.state != 'posted':
            raise UserError("Payment %s is not posted." % pay.name)
        liq, _cp, _wo = pay._seek_for_lines()
        if any(l.reconciled for l in liq):
            raise UserError("Payment %s is already matched." % pay.name)
        pay_lines |= liq
    total = sum(pay_lines.mapped('balance'))
    if not company.currency_id.is_zero(total - stmt_line.amount):
        raise UserError("Payments total %.2f but statement line is %.2f." % (total, stmt_line.amount))

    lines = []
    for l in pay_lines:
        bal = -l.balance
        lines.append((0, 0, {
            'account_id': l.account_id.id, 'partner_id': l.partner_id.id or False,
            'name': 'Cleared: %s' % l.move_id.name,
            'debit': max(bal, 0.0), 'credit': max(-bal, 0.0)}))
    sbal = -sum(suspense.mapped('balance'))
    lines.append((0, 0, {
        'account_id': suspense[0].account_id.id, 'name': 'Bank match: %s' % stmt_line.payment_ref,
        'debit': max(sbal, 0.0), 'credit': max(-sbal, 0.0)}))

    move = env['account.move'].with_company(company).create({
        'move_type': 'entry', 'journal_id': _general_journal(env, company).id,
        'date': stmt_line.date, 'ref': 'Bank match: %s' % stmt_line.payment_ref,
        'line_ids': lines})
    move.action_post()

    for account in pay_lines.mapped('account_id'):
        _ensure_reconcilable(account)
        (pay_lines.filtered(lambda l: l.account_id == account)
         | move.line_ids.filtered(lambda l: l.account_id == account and l.credit)).reconcile()
    susp_acc = suspense[0].account_id
    _ensure_reconcilable(susp_acc)
    (suspense | move.line_ids.filtered(lambda l: l.account_id == susp_acc)).reconcile()

    rec = env['pulse.bank.match'].create({
        'statement_line_id': stmt_line.id, 'kind': kind, 'note': note,
        'payment_ids': [(6, 0, payments.ids)], 'clearing_move_id': move.id})
    _payments_to_emit(env, payments)
    return rec


def book_to_account(stmt_line, account, note):
    """Unmatched line (fee, unexpected receipt): book it to a chosen account."""
    env = stmt_line.env
    if stmt_line.pulse_matched:
        raise UserError("Statement line is already matched.")
    company = stmt_line.journal_id.company_id
    liquidity, suspense, other = stmt_line._seek_for_lines()
    if not suspense:
        raise UserError("Statement line has no suspense line.")
    sbal = sum(suspense.mapped('balance'))
    move = env['account.move'].with_company(company).create({
        'move_type': 'entry', 'journal_id': _general_journal(env, company).id,
        'date': stmt_line.date, 'ref': 'Booked: %s' % stmt_line.payment_ref,
        'line_ids': [
            (0, 0, {'account_id': suspense[0].account_id.id, 'name': note,
                    'debit': max(-sbal, 0.0), 'credit': max(sbal, 0.0)}),
            (0, 0, {'account_id': account.id, 'name': note,
                    'debit': max(sbal, 0.0), 'credit': max(-sbal, 0.0)}),
        ]})
    move.action_post()
    susp_acc = suspense[0].account_id
    _ensure_reconcilable(susp_acc)
    (suspense | move.line_ids.filtered(lambda l: l.account_id == susp_acc)).reconcile()
    return env['pulse.bank.match'].create({
        'statement_line_id': stmt_line.id, 'kind': 'booked', 'note': note,
        'account_id': account.id, 'clearing_move_id': move.id})


def auto_match(env, journal=None, days=5):
    """Exact amount + date window + partner (when both known) + ONE candidate only."""
    Line, Payment = env['account.bank.statement.line'], env['account.payment']
    dom = [('pulse_matched', '=', False), ('amount', '>', 0)]
    pdom = [('payment_type', '=', 'inbound'), ('state', '=', 'posted'), ('is_matched', '=', False)]
    if journal:
        dom.append(('journal_id', '=', journal.id))
        pdom.append(('journal_id', '=', journal.id))
    pool = Payment.search(pdom)
    used = Payment
    matched = 0
    for line in Line.search(dom, order='date, id'):
        cands = (pool - used).filtered(
            lambda p: abs(p.amount - line.amount) < 0.005
            and abs((p.date - line.date).days) <= days
            and (not line.partner_id or not p.partner_id or line.partner_id == p.partner_id))
        if len(cands) != 1:
            continue
        try:
            with env.cr.savepoint():
                match(line, cands, kind='clean')
            used |= cands
            matched += 1
        except Exception as exc:
            _logger.warning("auto_match skipped %s: %s", line.payment_ref, exc)
    return matched


def find_split(env, line, pool, max_n=3, days=7):
    """Try combinations of up to max_n payments that add up to the statement line."""
    cands = pool.filtered(lambda p: abs((p.date - line.date).days) <= days)
    for n in range(2, max_n + 1):
        for combo in itertools.combinations(cands, n):
            if abs(sum(p.amount for p in combo) - line.amount) < 0.005:
                return env['account.payment'].browse([p.id for p in combo])
    return env['account.payment']


def exception_report(env, days=7, journal=None):
    """Statement lines older than N days that are still unmatched."""
    cutoff = fields.Date.context_today(env['account.bank.statement.line']) - fields.date.resolution * 0
    from datetime import timedelta
    cutoff = fields.Date.context_today(env['account.bank.statement.line']) - timedelta(days=days)
    dom = [('pulse_matched', '=', False), ('date', '<=', cutoff)]
    if journal:
        dom.append(('journal_id', '=', journal.id))
    lines = env['account.bank.statement.line'].search(dom, order='date')
    today = fields.Date.context_today(env['account.bank.statement.line'])
    return [{
        'id': l.id, 'date': str(l.date), 'age_days': (today - l.date).days,
        'ref': l.payment_ref, 'partner': l.partner_id.name or '', 'amount': l.amount,
    } for l in lines]