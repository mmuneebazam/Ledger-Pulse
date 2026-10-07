import logging

from odoo import models

from ..services import cash_bridge_engine

_logger = logging.getLogger(__name__)


class CrmLeadCash(models.Model):
    _inherit = 'crm.lead'

    def write(self, vals):
        res = super().write(vals)
        if ({'stage_id', 'probability'} & set(vals)
                and not self.env.context.get('pulse_no_invoice') and len(self) <= 50):
            for lead in self.filtered(
                    lambda l: l.probability == 100 and l.active and not l.pulse_bridge_ids):
                try:
                    with self.env.cr.savepoint():
                        # sudo only to DRAFT the invoice; posting still needs accounting rights
                        cash_bridge_engine.create_invoice_for_lead(lead.sudo())
                except Exception:
                    _logger.exception("LedgerPulse: invoice creation failed for lead %s", lead.id)
        return res