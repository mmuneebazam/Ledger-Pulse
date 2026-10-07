from odoo import api, fields, models


class AccountBankStatementLine(models.Model):
    _inherit = 'account.bank.statement.line'

    pulse_match_ids = fields.One2many('pulse.bank.match', 'statement_line_id')
    pulse_matched = fields.Boolean(
        compute='_compute_pulse_matched', store=True, index=True, string='Pulse Matched')

    @api.depends('pulse_match_ids')
    def _compute_pulse_matched(self):
        for rec in self:
            rec.pulse_matched = bool(rec.pulse_match_ids)