from odoo import api, fields, models


class PulseIdempotency(models.Model):
    _name = 'pulse.idempotency'
    _description = 'LedgerPulse Idempotency Record'
    _order = 'id desc'

    api_key_id = fields.Many2one(
        'pulse.api.key', required=True, ondelete='cascade', index=True)
    key = fields.Char(required=True)
    endpoint = fields.Char()
    request_hash = fields.Char(required=True)
    status_code = fields.Integer(required=True)
    response_body = fields.Text(required=True)

    _sql_constraints = [
        ('key_uniq', 'unique(api_key_id, key)',
         'This idempotency key was already used by this API key.'),
    ]

    @api.model
    def _gc_old_records(self):
        self.env.cr.execute(
            "DELETE FROM pulse_idempotency "
            "WHERE create_date < (NOW() AT TIME ZONE 'UTC') - INTERVAL '24 hours'")