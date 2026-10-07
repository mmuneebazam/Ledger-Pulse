from odoo import models

INCOME = ('income', 'income_other')
EXPENSE = ('expense', 'expense_depreciation', 'expense_direct_cost')
ASSET = ('asset_receivable', 'asset_cash', 'asset_current', 'asset_non_current',
         'asset_prepayments', 'asset_fixed')
LIABILITY = ('liability_payable', 'liability_credit_card', 'liability_current',
             'liability_non_current')
EQUITY = ('equity', 'equity_unaffected')


class PulseFinancials(models.AbstractModel):
    _name = 'pulse.financials'
    _description = 'LedgerPulse Financial Statements'

    def _rows(self, extra_domain):
        """One SQL GROUP BY per statement (read_group): stays fast at 100k+ lines."""
        env = self.env
        domain = [('parent_state', '=', 'posted'),
                  ('company_id', '=', env.company.id)] + extra_domain
        groups = env['account.move.line'].read_group(
            domain, ['debit:sum', 'credit:sum', 'balance:sum'], ['account_id'], lazy=False)
        accounts = env['account.account'].browse(
            [g['account_id'][0] for g in groups if g['account_id']])
        by_id = {a.id: a for a in accounts}
        rows = []
        for g in groups:
            if not g['account_id']:
                continue
            acc = by_id[g['account_id'][0]]
            rows.append({
                'account_id': acc.id, 'code': acc.code, 'name': acc.name,
                'type': acc.account_type, 'debit': g['debit'] or 0.0,
                'credit': g['credit'] or 0.0, 'balance': g['balance'] or 0.0})
        rows.sort(key=lambda r: r['code'] or '')
        return rows

    def trial_balance(self, date_to):
        rows = self._rows([('date', '<=', date_to)])
        td = sum(r['debit'] for r in rows)
        tc = sum(r['credit'] for r in rows)
        return {'rows': rows, 'total_debit': td, 'total_credit': tc,
                'balanced': self.env.company.currency_id.is_zero(td - tc)}

    def profit_and_loss(self, date_from, date_to):
        rows = self._rows([('date', '>=', date_from), ('date', '<=', date_to)])
        income = [dict(r, amount=-r['balance']) for r in rows if r['type'] in INCOME]
        expense = [dict(r, amount=r['balance']) for r in rows if r['type'] in EXPENSE]
        ti = sum(r['amount'] for r in income)
        te = sum(r['amount'] for r in expense)
        return {'income': income, 'expense': expense, 'total_income': ti,
                'total_expense': te, 'net': ti - te}

    def balance_sheet(self, date_to):
        rows = self._rows([('date', '<=', date_to)])
        assets = [r for r in rows if r['type'] in ASSET]
        liabs = [dict(r, amount=-r['balance']) for r in rows if r['type'] in LIABILITY]
        equity = [dict(r, amount=-r['balance']) for r in rows if r['type'] in EQUITY]
        earnings = -sum(r['balance'] for r in rows if r['type'] in INCOME + EXPENSE)
        ta = sum(r['balance'] for r in assets)
        tl = sum(r['amount'] for r in liabs)
        te = sum(r['amount'] for r in equity)
        return {
            'assets': assets, 'liabilities': liabs, 'equity': equity,
            'earnings': earnings, 'total_assets': ta, 'total_liabilities': tl,
            'total_equity': te,
            'balanced': self.env.company.currency_id.is_zero(ta - (tl + te + earnings)),
        }