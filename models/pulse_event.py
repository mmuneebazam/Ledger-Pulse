from odoo import fields, models

EVENT_TYPES = [
    ('lead.created', 'Lead created'),
    ('lead.scored', 'Lead scored'),
    ('sla.breached', 'SLA breached'),
    ('invoice.posted', 'Invoice posted'),
    ('payment.reconciled', 'Payment reconciled'),
    ('period.closed', 'Period closed'),
]


class PulseEvent(models.Model):
    _name = 'pulse.event'
    _description = 'LedgerPulse Outbound Event'
    _rec_name = 'event_type'
    _order = 'id desc'

    event_type = fields.Selection(EVENT_TYPES, required=True, index=True)
    res_model = fields.Char()
    res_id = fields.Integer()
    payload = fields.Text(help="JSON payload sent on the bus / webhook.")
    state = fields.Selection([
        ('pending', 'Pending'),
        ('dispatched', 'Dispatched'),
        ('failed', 'Failed'),
    ], default='pending', required=True, index=True)
    retry_count = fields.Integer(default=0)
    company_id = fields.Many2one(
        'res.company', ondelete='set null',
        default=lambda self: self.env.company)
    team_id = fields.Many2one('crm.team', ondelete='set null')
    dispatched_at = fields.Datetime()
    error = fields.Text()

    def init(self):
        self._cr.execute(
            "CREATE INDEX IF NOT EXISTS pulse_event_state_create_idx "
            "ON pulse_event (state, create_date)")