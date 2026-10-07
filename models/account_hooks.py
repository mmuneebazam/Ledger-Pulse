import logging

from odoo import api, models

from ..services import event_bus

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        try:
            with self.env.cr.savepoint():
                bridges = self.env['pulse.cash.bridge'].sudo().search(
                    [('move_id', 'in', posted.ids)])
                for b in bridges:
                    event_bus.emit(self.env, 'invoice.posted', b.lead_id, {
                        'id': b.lead_id.id, 'name': b.move_id.name,
                        'invoice_id': b.move_id.id, 'amount_total': b.move_id.amount_total})
        except Exception:
            _logger.exception("LedgerPulse: invoice.posted event failed")
        return posted


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        try:
            with self.env.cr.savepoint():
                moves = partials.debit_move_id.move_id | partials.credit_move_id.move_id
                bridges = self.env['pulse.cash.bridge'].sudo().search(
                    [('move_id', 'in', moves.ids)])
                for b in bridges:
                    event_bus.emit(self.env, 'payment.reconciled', b.lead_id, {
                        'id': b.lead_id.id, 'name': b.move_id.name, 'invoice_id': b.move_id.id})
        except Exception:
            _logger.exception("LedgerPulse: payment.reconciled event failed")
        return partials