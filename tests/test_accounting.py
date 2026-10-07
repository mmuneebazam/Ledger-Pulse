from datetime import date, timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.ledger_pulse.services import accounting_setup, cash_bridge_engine


@tagged('post_install', '-at_install', 'ledger_pulse')
class TestLedgerPulseAccounting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.setup = accounting_setup.ensure_demo_setup(cls.env, cls.company)

    def _bridge(self, partner_key='standard_partner', revenue=1000.0):
        lead = self.env['crm.lead'].with_context(tracking_disable=True).create({
            'name': 'Test lead', 'type': 'opportunity', 'expected_revenue': revenue,
            'partner_id': self.setup[partner_key].id})
        bridge = cash_bridge_engine.create_invoice_for_lead(lead)
        self.assertTrue(bridge, "bridge invoice was not created")
        return lead, bridge

    def test_invoice_balances_and_hits_expected_accounts(self):
        _lead, bridge = self._bridge()
        move = bridge.move_id
        move.action_post()
        cur = move.company_currency_id
        self.assertTrue(cur.is_zero(sum(move.line_ids.mapped('balance'))), "entry must balance")
        types = move.line_ids.mapped('account_id.account_type')
        self.assertIn('asset_receivable', types)
        self.assertTrue(any(t in ('income', 'income_other') for t in types))
        self.assertIn(self.setup['tax_account'], move.line_ids.mapped('account_id'))
        self.assertAlmostEqual(move.amount_total, 1170.0, places=2)

    def test_fiscal_position_swaps_tax(self):
        _lead, bridge = self._bridge('exempt_partner')
        move = bridge.move_id
        move.action_post()
        self.assertNotIn(self.setup['tax_account'], move.line_ids.mapped('account_id'))
        self.assertAlmostEqual(move.amount_total, 1000.0, places=2)

    def test_partial_payment(self):
        _lead, bridge = self._bridge()
        move = bridge.move_id
        move.action_post()
        paid = round(move.amount_total * 0.6, 2)
        cash_bridge_engine.register_payment(move, amount=paid)
        self.assertEqual(move.payment_state, 'partial')
        self.assertAlmostEqual(move.amount_residual, round(move.amount_total - paid, 2), places=2)

    def test_full_payment_awaits_bank(self):
        _lead, bridge = self._bridge()
        move = bridge.move_id
        move.action_post()
        cash_bridge_engine.register_payment(move)
        self.assertIn(move.payment_state, ('in_payment', 'paid'))

    def test_credit_note_reduces_original_balance(self):
        _lead, bridge = self._bridge()
        move = bridge.move_id
        move.action_post()
        cash_bridge_engine.issue_credit_note(move, amount=200.0, reason='Downgrade')
        self.assertAlmostEqual(move.amount_residual, 1170.0 - 234.0, places=2)

    def test_tax_inclusive_and_exclusive_same_net(self):
        product = self.setup['product']
        results = []
        for tax, price in ((self.setup['vat'], 100.0), (self.setup['vat_incl'], 117.0)):
            inv = self.env['account.move'].create({
                'move_type': 'out_invoice', 'partner_id': self.setup['standard_partner'].id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {
                    'product_id': product.id, 'name': 'x', 'quantity': 1, 'price_unit': price,
                    'tax_ids': [(6, 0, [tax.id])]})]})
            results.append((inv.amount_untaxed, inv.amount_tax))
        self.assertAlmostEqual(results[0][0], results[1][0], places=2)
        self.assertAlmostEqual(results[0][1], results[1][1], places=2)

    def test_fx_gain_is_booked_with_correct_sign(self):
        c = self.company
        if not c.income_currency_exchange_account_id or not c.expense_currency_exchange_account_id:
            self.skipTest("Company has no exchange gain/loss accounts configured")
        today = fields.Date.today()
        inv, _pay = accounting_setup.fx_invoice_with_payment(
            self.env, self.setup['standard_partner'], today - timedelta(days=40), today,
            0.90, 0.80, 1000.0)
        partials = inv.line_ids.matched_debit_ids | inv.line_ids.matched_credit_ids
        exchange_moves = partials.exchange_move_id
        self.assertTrue(exchange_moves, "an exchange difference entry must exist")
        gain = exchange_moves.line_ids.filtered(
            lambda l: l.account_id == c.income_currency_exchange_account_id)
        self.assertTrue(gain)
        self.assertGreater(sum(gain.mapped('credit')) - sum(gain.mapped('debit')), 0)

    def test_close_is_blocked_by_draft_invoice(self):
        self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.setup['standard_partner'].id,
            'invoice_date': date(2001, 3, 15),
            'invoice_line_ids': [(0, 0, {
                'product_id': self.setup['product'].id, 'name': 'old draft',
                'quantity': 1, 'price_unit': 10.0})]})
        wiz = self.env['pulse.close.wizard'].create({'period': '2001-03'})
        wiz.action_run_checks()
        self.assertFalse(wiz.can_lock)
        by_task = {c['task']: c for c in wiz._checks()}
        self.assertFalse(by_task['no_draft_invoices']['ok'])

    def test_statements_are_consistent(self):
        fin = self.env['pulse.financials']
        today = fields.Date.today()
        tb = fin.trial_balance(today)
        self.assertTrue(tb['balanced'], "trial balance must balance")
        bs = fin.balance_sheet(today)
        self.assertTrue(bs['balanced'], "assets must equal liabilities + equity + earnings")
        pl = fin.profit_and_loss(today.replace(day=1) - timedelta(days=400), today)
        self.assertAlmostEqual(pl['net'], pl['total_income'] - pl['total_expense'], places=2)