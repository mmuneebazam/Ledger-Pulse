from odoo import fields, models


class CrmLeadScoreRule(models.Model):
    _name = 'crm.lead.score.rule'
    _description = 'CRM Lead Scoring Rule'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one(
        'ir.model.fields', string='Lead Field', required=True,
        ondelete='cascade', domain=[('model', '=', 'crm.lead')])
    field_name = fields.Char(related='field_id.name', store=True, readonly=True)
    operator = fields.Selection([
        ('eq', 'Equals'),
        ('neq', 'Not equals'),
        ('gt', 'Greater than'),
        ('gte', 'Greater or equal'),
        ('lt', 'Less than'),
        ('lte', 'Less or equal'),
        ('contains', 'Contains'),
        ('not_contains', 'Does not contain'),
        ('set', 'Is set'),
        ('not_set', 'Is not set'),
    ], required=True, default='eq')
    value = fields.Char()
    points = fields.Integer(required=True, default=10)
    company_id = fields.Many2one('res.company', ondelete='cascade')
    active = fields.Boolean(default=True)