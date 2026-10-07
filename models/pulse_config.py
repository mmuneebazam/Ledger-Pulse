from odoo import api, fields, models


class PulseConfig(models.Model):
    _name = 'pulse.config'
    _description = 'LedgerPulse Configuration'

    name = fields.Char(required=True, default='Default')
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade',
        default=lambda self: self.env.company)
    api_version = fields.Char(required=True, default='v1')
    rate_limit_per_min = fields.Integer(required=True, default=60)
    jwt_secret_ref = fields.Char(
        string='JWT Secret Reference',
        help="Name of the system parameter / env var holding the JWT secret. "
             "Never store the secret itself here.")
    bus_channel = fields.Char(required=True, default='ledger_pulse')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('company_uniq', 'unique(company_id)',
         'Only one LedgerPulse configuration per company.'),
        ('rate_limit_positive', 'CHECK(rate_limit_per_min > 0)',
         'Rate limit must be greater than zero.'),
    ]

    @api.model
    def get_config(self, company=None):
        company = company or self.env.company
        cfg = self.sudo().search([('company_id', '=', company.id)], limit=1)
        if not cfg:
            cfg = self.sudo().create({'company_id': company.id})
        return cfg