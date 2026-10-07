from odoo import fields, models


class PulseCloseChecklist(models.Model):
    _name = 'pulse.close.checklist'
    _description = 'Period Close Checklist'
    _order = 'period desc, id'

    period = fields.Char(required=True, help="e.g. 2026-02")
    date_from = fields.Date()
    date_to = fields.Date()
    task = fields.Selection([
        ('bank_reconciled', 'All bank statement lines reconciled'),
        ('no_draft_invoices', 'No draft invoices in period'),
        ('lock_period', 'Period locked'),
        ('trial_balance', 'Trial balance generated'),
    ], required=True)
    done = fields.Boolean(default=False)
    done_by = fields.Many2one('res.users', readonly=True, ondelete='set null')
    done_at = fields.Datetime(readonly=True)
    note = fields.Text()
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade',
        default=lambda self: self.env.company)

    _sql_constraints = [
        ('period_task_uniq', 'unique(period, task, company_id)',
         'This task already exists for this period.'),
    ]

    def action_mark_done(self):
        self.write({
            'done': True,
            'done_by': self.env.uid,
            'done_at': fields.Datetime.now(),
        })