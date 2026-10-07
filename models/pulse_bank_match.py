from odoo import api, fields, models

from ..services import bank_recon_engine


class PulseBankMatch(models.Model):
    _name = 'pulse.bank.match'
    _description = 'Bank Statement Match'
    _order = 'id desc'

    statement_line_id = fields.Many2one(
        'account.bank.statement.line', required=True, ondelete='restrict', index=True)
    kind = fields.Selection([
        ('clean', 'Clean match'), ('split', 'Split match'), ('booked', 'Booked to account')],
        required=True)
    payment_ids = fields.Many2many(
        'account.payment', 'pulse_bank_match_payment_rel', 'match_id', 'payment_id')
    clearing_move_id = fields.Many2one('account.move', ondelete='restrict')
    account_id = fields.Many2one('account.account', string='Booked To')
    note = fields.Char()
    company_id = fields.Many2one(
        'res.company', related='statement_line_id.journal_id.company_id', store=True)

    _sql_constraints = [
        ('stmt_uniq', 'unique(statement_line_id)', 'This statement line is already matched.'),
    ]

    @api.model
    def _cron_auto_match(self):
        bank_recon_engine.auto_match(self.env)