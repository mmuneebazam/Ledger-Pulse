from odoo import api, fields, models

from ..services import accounting_setup


class PulseBudget(models.Model):
    _name = 'pulse.budget'
    _description = 'Team Revenue Budget'
    _order = 'date_from desc, id'

    name = fields.Char(required=True)
    team_id = fields.Many2one('crm.team', required=True, ondelete='cascade')
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company, ondelete='cascade')
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    planned_revenue = fields.Float(required=True)
    actual_revenue = fields.Float(compute='_compute_actual')
    variance = fields.Float(compute='_compute_actual', help="Actual minus planned")
    achievement = fields.Float(compute='_compute_actual', string='Achievement %')

    _sql_constraints = [
        ('dates_ok', 'CHECK(date_to >= date_from)', 'End date must be after start date.'),
    ]

    @api.depends('team_id', 'date_from', 'date_to', 'planned_revenue')
    def _compute_actual(self):
        Line = self.env['account.analytic.line'].sudo()
        for b in self:
            actual = 0.0
            if b.team_id and b.date_from and b.date_to:
                acc = accounting_setup.find_team_analytic_account(
                    self.env, b.team_id, b.company_id)
                if acc:
                    lines = Line.search([
                        ('account_id', '=', acc.id), ('date', '>=', b.date_from),
                        ('date', '<=', b.date_to), ('amount', '>', 0)])
                    actual = sum(lines.mapped('amount'))
            b.actual_revenue = actual
            b.variance = actual - b.planned_revenue
            b.achievement = (actual / b.planned_revenue * 100.0) if b.planned_revenue else 0.0