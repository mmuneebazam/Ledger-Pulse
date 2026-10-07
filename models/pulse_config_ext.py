from odoo import fields, models


class PulseConfigExt(models.Model):
    _inherit = 'pulse.config'

    invoice_product_id = fields.Many2one(
        'product.product', string='Default Invoice Product', domain=[('sale_ok', '=', True)])
    invoice_payment_term_id = fields.Many2one(
        'account.payment.term', string='Default Payment Terms')