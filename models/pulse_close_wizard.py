from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import html_escape

from ..services import event_bus

INVOICE_TYPES = ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']


def fmt(x):
    return '{:,.2f}'.format(x or 0.0)


def table(headers, rows):
    out = ['<table class="table table-sm"><thead><tr>']
    out += ['<th>%s</th>' % html_escape(h) for h in headers]
    out.append('</tr></thead><tbody>')
    for row in rows:
        out.append('<tr>' + ''.join('<td>%s</td>' % html_escape(str(c)) for c in row) + '</tr>')
    out.append('</tbody></table>')
    return ''.join(out)


class PulseCloseWizard(models.TransientModel):
    _name = 'pulse.close.wizard'
    _description = 'Period Close Wizard'

    period = fields.Char(required=True, default=lambda self: self._default_period(),
                         help="YYYY-MM")
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(compute='_compute_range')
    date_to = fields.Date(compute='_compute_range')
    can_lock = fields.Boolean(readonly=True)
    result_html = fields.Html(readonly=True, sanitize=False)

    def _default_period(self):
        first = fields.Date.context_today(self).replace(day=1)
        return (first - timedelta(days=1)).strftime('%Y-%m')

    @api.depends('period')
    def _compute_range(self):
        for w in self:
            try:
                y, m = [int(x) for x in (w.period or '').split('-')]
                start = date(y, m, 1)
                end = start + relativedelta(months=1) - timedelta(days=1)
            except Exception:
                start = end = False
            w.date_from, w.date_to = start, end

    @api.onchange('period')
    def _onchange_period(self):
        self.can_lock = False
        self.result_html = False

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}

    # ---------------------------------------------------------- checks
    def _checks(self):
        self.ensure_one()
        if not self.date_from:
            raise UserError(_("Period must look like 2026-02."))
        env, cid = self.env, self.company_id.id
        df, dt = self.date_from, self.date_to

        drafts = env['account.move'].search([
            ('company_id', '=', cid), ('state', '=', 'draft'),
            ('move_type', 'in', INVOICE_TYPES),
            '|', '&', ('invoice_date', '>=', df), ('invoice_date', '<=', dt),
            '&', ('date', '>=', df), ('date', '<=', dt)])
        unmatched = env['account.bank.statement.line'].search([
            ('journal_id.company_id', '=', cid), ('date', '>=', df), ('date', '<=', dt),
            ('pulse_matched', '=', False)])
        return [
            {'task': 'no_draft_invoices', 'ok': not drafts,
             'detail': _('No draft invoices in %s', self.period) if not drafts else
             _('%d draft invoice(s): %s', len(drafts),
               ', '.join((d.name if d.name != '/' else 'draft #%d' % d.id) for d in drafts[:10]))},
            {'task': 'bank_reconciled', 'ok': not unmatched,
             'detail': _('All bank statement lines matched') if not unmatched else
             _('%d unmatched statement line(s): %s', len(unmatched),
               '; '.join('%s %s' % (l.payment_ref, fmt(l.amount)) for l in unmatched[:10]))},
        ]

    def _set_task(self, task, ok, note):
        Check = self.env['pulse.close.checklist'].sudo()
        rec = Check.search([('period', '=', self.period), ('task', '=', task),
                            ('company_id', '=', self.company_id.id)], limit=1)
        vals = {'done': ok, 'note': note, 'date_from': self.date_from, 'date_to': self.date_to,
                'done_by': self.env.uid if ok else False,
                'done_at': fields.Datetime.now() if ok else False}
        if rec:
            rec.write(vals)
        else:
            Check.create(dict(vals, period=self.period, task=task,
                              company_id=self.company_id.id))

    def action_run_checks(self):
        self.ensure_one()
        checks = self._checks()
        for c in checks:
            self._set_task(c['task'], c['ok'], c['detail'])
        self.can_lock = all(c['ok'] for c in checks)
        self.result_html = table(
            ['Check', 'Result', 'Details'],
            [(c['task'], 'PASS' if c['ok'] else 'BLOCKED', c['detail']) for c in checks])
        return self._reopen()

    def action_lock(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_manager'):
            raise UserError(_("Only Accounting Advisers can lock a period."))
        checks = self._checks()
        for c in checks:
            self._set_task(c['task'], c['ok'], c['detail'])
        if not all(c['ok'] for c in checks):
            raise UserError(_("Cannot lock the period: ") +
                            '; '.join(c['detail'] for c in checks if not c['ok']))
        company = self.company_id
        current = company.fiscalyear_lock_date
        if current and current >= self.date_to:
            raise UserError(_("The books are already locked up to %s.", current))
        company.sudo().write({'fiscalyear_lock_date': self.date_to})
        self._set_task('lock_period', True, _('Locked up to %s', self.date_to))
        event_bus.emit(self.env, 'period.closed', None, {'period': self.period})
        self.can_lock = False
        self.result_html = (self.result_html or '') + (
            '<p><b>Period %s is locked (no entries up to %s).</b></p>' % (self.period, self.date_to))
        return self._reopen()

    def action_statements(self):
        self.ensure_one()
        fin = self.env['pulse.financials']
        tb = fin.trial_balance(self.date_to)
        pl = fin.profit_and_loss(self.date_from, self.date_to)
        bs = fin.balance_sheet(self.date_to)

        html = ['<h4>Trial balance up to %s</h4>' % self.date_to]
        html.append(table(['Code', 'Account', 'Debit', 'Credit'],
                          [(r['code'], r['name'], fmt(r['debit']), fmt(r['credit']))
                           for r in tb['rows']] +
                          [('', 'TOTAL', fmt(tb['total_debit']), fmt(tb['total_credit']))]))
        html.append('<p>Balanced: <b>%s</b></p>' % ('YES' if tb['balanced'] else 'NO'))
        html.append('<h4>Profit &amp; Loss %s to %s</h4>' % (self.date_from, self.date_to))
        html.append(table(['Account', 'Amount'],
                          [(r['name'], fmt(r['amount'])) for r in pl['income']] +
                          [('TOTAL INCOME', fmt(pl['total_income']))] +
                          [(r['name'], fmt(r['amount'])) for r in pl['expense']] +
                          [('TOTAL EXPENSE', fmt(pl['total_expense'])),
                           ('NET PROFIT', fmt(pl['net']))]))
        html.append('<h4>Balance sheet at %s</h4>' % self.date_to)
        html.append(table(['Section', 'Amount'], [
            ('Total assets', fmt(bs['total_assets'])),
            ('Total liabilities', fmt(bs['total_liabilities'])),
            ('Total equity', fmt(bs['total_equity'])),
            ('Earnings (unallocated)', fmt(bs['earnings'])),
            ('Assets = Liabilities + Equity + Earnings?', 'YES' if bs['balanced'] else 'NO')]))
        self.result_html = ''.join(html)
        self._set_task('trial_balance', tb['balanced'] and bs['balanced'],
                       _('TB debit %s / credit %s', fmt(tb['total_debit']), fmt(tb['total_credit'])))
        return self._reopen()