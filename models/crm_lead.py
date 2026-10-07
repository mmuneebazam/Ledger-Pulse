import logging

from odoo import api, fields, models

from ..services import assignment_engine, event_bus, scoring_engine, sla_engine

_logger = logging.getLogger(__name__)
MAX_INLINE = 50  # bigger batches are handled by background jobs, not inline hooks


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    pulse_score = fields.Integer(string='Pulse Score', default=0, index=True, copy=False)
    pulse_score_explanation = fields.Text(readonly=True, copy=False)
    sla_deadline = fields.Datetime(index=True, copy=False)
    sla_state = fields.Selection([
        ('none', 'No SLA'),
        ('ok', 'On Track'),
        ('breached', 'Breached'),
    ], default='none', index=True, copy=False)
    source_channel = fields.Selection([
        ('website', 'Website'),
        ('api', 'API'),
        ('partner', 'Partner Portal'),
        ('email', 'Email'),
        ('phone', 'Phone'),
        ('other', 'Other'),
    ], default='other', index=True)

    pulse_bridge_ids = fields.One2many('pulse.cash.bridge', 'lead_id', string='Cash Bridges')
    pulse_invoice_state = fields.Selection([
        ('none', 'No Invoice'),
        ('draft', 'Draft Invoice'),
        ('posted', 'Posted / Unpaid'),
        ('partial', 'Partially Paid'),
        ('in_payment', 'Paid - Awaiting Bank'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
    ], compute='_compute_pulse_invoice_state', string='Invoice State')

    @api.depends('pulse_bridge_ids.state')
    def _compute_pulse_invoice_state(self):
        for lead in self:
            bridges = lead.pulse_bridge_ids.sorted('id')
            lead.pulse_invoice_state = bridges[-1].state if bridges else 'none'

    # ------------------------------------------------------------ hooks
    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        if not self.env.context.get('pulse_skip') and len(leads) <= MAX_INLINE:
            leads._pulse_post_create()
        return leads

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('pulse_skip') and len(self) <= MAX_INLINE:
            if scoring_engine.watched_fields(self.env) & set(vals):
                for lead in self.with_context(pulse_skip=True):
                    scoring_engine.score_lead(lead, emit=True)
        return res

    def _pulse_post_create(self):
        for lead in self.with_context(pulse_skip=True):
            try:
                with self.env.cr.savepoint():
                    assignment_engine.assign(lead)
                    sla_engine.apply_sla(lead)
                    scoring_engine.score_lead(lead, emit=False)
                    payload = event_bus.lead_payload(lead)
                    event_bus.emit(self.env, 'lead.created', lead, payload)
                    event_bus.emit(self.env, 'lead.scored', lead, payload)
            except Exception:
                _logger.exception("LedgerPulse post-create hook failed for lead %s", lead.id)

    # ------------------------------------------------------------ crons
    @api.model
    def _cron_pulse_sweep_sla(self):
        sla_engine.sweep_breached(self.env)

    @api.model
    def _cron_pulse_nightly_rescore(self):
        scoring_engine.bulk_rescore(self.env)