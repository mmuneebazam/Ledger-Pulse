from odoo import fields, models


class PulseJob(models.Model):
    _name = 'pulse.job'
    _description = 'LedgerPulse Background Job'
    _order = 'id desc'

    name = fields.Char(required=True)
    state = fields.Selection([
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], default='queued', required=True, index=True)
    args = fields.Text()
    result = fields.Text()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    error = fields.Text()
    company_id = fields.Many2one(
        'res.company', ondelete='set null',
        default=lambda self: self.env.company)

    def start(self):
        self.write({'state': 'running', 'started_at': fields.Datetime.now()})

    def finish(self, result=''):
        self.write({'state': 'done', 'result': result,
                    'finished_at': fields.Datetime.now()})

    def fail(self, error=''):
        self.write({'state': 'failed', 'error': error,
                    'finished_at': fields.Datetime.now()})