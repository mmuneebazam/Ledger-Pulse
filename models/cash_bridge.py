from odoo import api, fields, models

from ..services import cash_bridge_engine


class PulseCashBridge(models.Model):
    _name = 'pulse.cash.bridge'
    _description = 'CRM-to-Cash Bridge'
    _order = 'id desc'

    # restrict: a lead / invoice / payment that is part of the audit trail
    # can never be silently deleted from under the bridge record.
    lead_id = fields.Many2one('crm.lead', required=True, ondelete='restrict', index=True)
    move_id = fields.Many2one('account.move', string='Invoice', ondelete='restrict', index=True)
    payment_id = fields.Many2one('account.payment', ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', related='lead_id.company_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft Invoice'),
        ('posted', 'Posted / Unpaid'),
        ('partial', 'Partially Paid'),
        ('in_payment', 'Paid - Awaiting Bank'),
        ('paid', 'Paid'),
        ('cancel', 'Cancelled'),
    ], compute='_compute_state', store=True, index=True)
    linked_at = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('lead_move_uniq', 'unique(lead_id, move_id)',
         'This invoice is already linked to this lead.'),
    ]

    @api.depends('move_id.state', 'move_id.payment_state')
    def _compute_state(self):
        for rec in self:
            move = rec.move_id
            if not move or move.state == 'draft':
                rec.state = 'draft'
            elif move.state == 'cancel':
                rec.state = 'cancel'
            elif move.payment_state == 'paid':
                rec.state = 'paid'
            elif move.payment_state == 'in_payment':
                rec.state = 'in_payment'
            elif move.payment_state == 'partial':
                rec.state = 'partial'
            else:
                rec.state = 'posted'

    # Posting runs as the CURRENT user, so Odoo's own accounting ACL decides.
    def action_post_invoice(self):
        for rec in self:
            if rec.move_id.state == 'draft':
                rec.move_id.action_post()

    def action_open_invoice(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'res_id': self.move_id.id, 'view_mode': 'form'}

    def register_payment(self, amount=None, date=None, reference=None):
        self.ensure_one()
        return cash_bridge_engine.register_payment(self.move_id, amount, date, reference)

    def issue_credit_note(self, amount=None, reason='Service downgrade'):
        self.ensure_one()
        return cash_bridge_engine.issue_credit_note(self.move_id, amount, reason)