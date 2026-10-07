from odoo import fields, models


class PulseSlaPolicy(models.Model):
    _name = 'pulse.sla.policy'
    _description = 'LedgerPulse SLA Policy'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    team_id = fields.Many2one('crm.team', ondelete='cascade')
    source_channel = fields.Selection([
        ('website', 'Website'),
        ('api', 'API'),
        ('partner', 'Partner Portal'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('other', 'Other'),
    ])
    hours = fields.Float(required=True, default=24.0, help="Hours until the SLA deadline.")
    company_id = fields.Many2one('res.company', ondelete='cascade')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('hours_positive', 'CHECK(hours > 0)', 'SLA hours must be greater than zero.'),
    ]