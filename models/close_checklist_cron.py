from odoo import api, models

from ..services import event_bus


class PulseCloseChecklistCron(models.Model):
    _inherit = 'pulse.close.checklist'

    @api.model
    def _cron_emit_period_closed(self):
        """Once a period is locked, make sure a period.closed event exists for it."""
        Event = self.env['pulse.event'].sudo()
        for rec in self.sudo().search([('task', '=', 'lock_period'), ('done', '=', True)]):
            marker = '"period": "%s"' % rec.period
            if Event.search_count([('event_type', '=', 'period.closed'),
                                   ('payload', 'ilike', marker),
                                   ('company_id', '=', rec.company_id.id)]):
                continue
            event_bus.emit(self.with_company(rec.company_id).env, 'period.closed', None,
                           {'period': rec.period})