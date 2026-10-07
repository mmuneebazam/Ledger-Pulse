from odoo import api, fields, models

from ..services import event_bus

HIGH_SCORE_THRESHOLD = 70


class PulseDashboard(models.AbstractModel):
    _name = 'pulse.dashboard'
    _description = 'LedgerPulse Dashboard Data'

    @api.model
    def get_snapshot(self, filters=None):
        filters = filters or {}
        env = self.env
        company = env.company
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        Lead = env['crm.lead']
        base = [('company_id', 'in', [False, company.id])]

        kpis = {
            'new_leads_today': Lead.search_count(base + [('create_date', '>=', today_start)]),
            'sla_breaches': Lead.search_count(base + [('sla_state', '=', 'breached')]),
            'won_this_month': 0,
            'won_revenue': 0.0,
            'overdue_invoices': 0,
            'overdue_amount': 0.0,
        }
        won_domain = base + [('probability', '=', 100), ('date_closed', '>=', month_start)]
        kpis['won_this_month'] = Lead.search_count(won_domain)
        grp = Lead.read_group(won_domain, ['expected_revenue:sum'], [])
        kpis['won_revenue'] = (grp[0].get('expected_revenue') or 0.0) if grp else 0.0

        # Respect accounting security: finance numbers only for accounting readers.
        can_see_finance = env.user.has_group('account.group_account_readonly')
        overdue_ids = set()
        if can_see_finance:
            Move = env['account.move'].sudo()
            due_domain = [
                ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('invoice_date_due', '<', today), ('company_id', '=', company.id),
            ]
            moves = Move.search(due_domain)
            overdue_ids = set(moves.ids)
            kpis['overdue_invoices'] = len(moves)
            kpis['overdue_amount'] = sum(moves.mapped('amount_residual'))

        domain = list(base)
        if filters.get('channel'):
            domain.append(('source_channel', '=', filters['channel']))
        if filters.get('min_score'):
            domain.append(('pulse_score', '>=', int(filters['min_score'])))
        leads = Lead.search(domain, order='pulse_score desc, id desc', limit=60)

        lead_rows = []
        for lead in leads:
            row = event_bus.lead_payload(lead)
            badge = 'none'
            if can_see_finance and lead.pulse_bridge_ids:
                bridge = lead.sudo().pulse_bridge_ids.sorted('id')[-1]
                badge = 'overdue' if bridge.move_id.id in overdue_ids else bridge.state
            row['invoice_badge'] = badge
            lead_rows.append(row)

        if env.user.has_group('ledger_pulse.group_pulse_manager'):
            channels = ['ledger_pulse_c%d' % company.id]
        else:
            teams = env['crm.team'].search([('member_ids', 'in', env.uid)])
            channels = ['ledger_pulse_c%d_t%d' % (company.id, t.id) for t in teams]

        closed = env['pulse.close.checklist'].sudo().search([
            ('task', '=', 'lock_period'), ('done', '=', True),
            ('company_id', '=', company.id)], order='period desc', limit=3)

        cur = company.currency_id
        return {
            'kpis': kpis,
            'leads': lead_rows,
            'channels': channels,
            'can_see_finance': can_see_finance,
            'high_score': HIGH_SCORE_THRESHOLD,
            'closed_periods': closed.mapped('period'),
            'currency': {'symbol': cur.symbol, 'position': cur.position,
                         'decimals': cur.decimal_places},
        }