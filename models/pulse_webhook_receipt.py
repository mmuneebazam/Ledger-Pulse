from odoo import fields, models


class PulseWebhookReceipt(models.Model):
    _name = 'pulse.webhook.receipt'
    _description = 'Inbound Webhook Receipt (dedupe)'
    _order = 'id desc'

    event_id = fields.Char(required=True, index=True)
    event_type = fields.Char()
    move_id = fields.Many2one('account.move', ondelete='set null')
    payment_id = fields.Many2one('account.payment', ondelete='set null')
    amount = fields.Float()
    company_id = fields.Many2one('res.company', ondelete='set null')
    status = fields.Selection([
        ('received', 'Received'), ('registered', 'Payment registered'),
        ('rejected', 'Rejected')], default='received')

    _sql_constraints = [
        ('event_uniq', 'unique(event_id)', 'This webhook event was already received.'),
    ]