from odoo import fields, models


class PulseRequestLog(models.Model):
    _name = 'pulse.request.log'
    _description = 'LedgerPulse API Request Log'
    _order = 'id desc'

    api_key_id = fields.Many2one(
        'pulse.api.key', ondelete='set null', index=True)
    company_id = fields.Many2one(
        'res.company', ondelete='set null',
        default=lambda self: self.env.company)
    endpoint = fields.Char(index=True)
    method = fields.Char()
    status_code = fields.Integer(index=True)
    latency_ms = fields.Integer()