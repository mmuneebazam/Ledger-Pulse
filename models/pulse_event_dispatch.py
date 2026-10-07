from datetime import timedelta

from odoo import api, fields, models

from ..services import event_bus


class PulseEvent(models.Model):
    _inherit = 'pulse.event'

    @api.model
    def _cron_retry_failed(self):
        stale = fields.Datetime.now() - timedelta(minutes=5)
        events = self.search([
            ('retry_count', '<', 5),
            '|', ('state', '=', 'failed'),
            '&', ('state', '=', 'pending'), ('create_date', '<', stale),
        ], limit=200)
        for ev in events:
            event_bus.dispatch(ev)